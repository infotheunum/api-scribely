from __future__ import annotations

from datetime import UTC, datetime

import grpc
from common.grpc_client import check_rewrite_health
from common.integration_reasons import (
    REASON_DISPATCH_DISABLED,
    REASON_INGESTION_DISABLED,
    REASON_OK,
    REASON_OPENROUTER_NO_KEYS,
    REASON_PIPELINE_DEGRADED,
    REASON_QUEUE_EMPTY,
    REASON_REWRITE_UNAVAILABLE,
    human_reason_message,
)
from common.pipeline_telemetry import (
    KEY_LAST_DISPATCH_AT,
    KEY_LAST_DISPATCH_DISPATCHED,
    KEY_LAST_DISPATCH_FAILED,
    KEY_LAST_ERROR_AT,
    KEY_LAST_ERROR_CODE,
    KEY_LAST_ERROR_MESSAGE,
)
from db.app_settings import get_setting
from db.enums import DraftStatus, TopicStatus
from db.models import Draft, DraftExportLog, LLMRotationUsage, NewsCluster
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def count_unconsumed_drafts(
    db: Session,
    *,
    statuses: list[str],
) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Draft)
        .outerjoin(DraftExportLog, DraftExportLog.draft_id == Draft.id)
        .where(Draft.status.in_(statuses), DraftExportLog.draft_id.is_(None))
    ) or 0


def count_undrafted_in_topic_clusters(db: Session) -> int:
    drafted_ids = select(Draft.cluster_id)
    return (
        db.scalar(
            select(func.count())
            .select_from(NewsCluster)
            .where(
                NewsCluster.topic_status == TopicStatus.IN_TOPIC,
                NewsCluster.id.not_in(drafted_ids),
            )
        )
        or 0
    )


def _rewrite_reachable(channel: grpc.Channel | None) -> bool:
    if channel is None:
        return False
    try:
        return check_rewrite_health(channel)
    except grpc.RpcError:
        return False


def _openrouter_keys_configured(db: Session) -> int:
    return int(get_setting(db, "openrouter.keys_configured", 0) or 0)


def build_pipeline_status(
    db: Session,
    *,
    rewrite_channel: grpc.Channel | None = None,
    unconsumed_drafts: int | None = None,
) -> dict:
    """Snapshot for GET /integrations/theunum/v1/status and list `meta`."""
    if unconsumed_drafts is None:
        unconsumed_drafts = count_unconsumed_drafts(
            db,
            statuses=[DraftStatus.READY_FOR_REVIEW.value, DraftStatus.NEEDS_FIX.value],
        )

    undrafted = count_undrafted_in_topic_clusters(db)
    poll_enabled = bool(get_setting(db, "pipeline.poll_enabled", True))
    dispatch_enabled = bool(get_setting(db, "pipeline.dispatch_enabled", True))
    rewrite_reachable = _rewrite_reachable(rewrite_channel)
    keys_configured = _openrouter_keys_configured(db)

    last_error_code = str(get_setting(db, KEY_LAST_ERROR_CODE, REASON_OK) or REASON_OK)
    last_error_message = str(get_setting(db, KEY_LAST_ERROR_MESSAGE, "") or "")
    last_error_at = get_setting(db, KEY_LAST_ERROR_AT, None)
    last_dispatch_at = get_setting(db, KEY_LAST_DISPATCH_AT, None)
    last_dispatch_dispatched = get_setting(db, KEY_LAST_DISPATCH_DISPATCHED, 0)
    last_dispatch_failed = get_setting(db, KEY_LAST_DISPATCH_FAILED, 0)

    reason_code = REASON_OK
    pipeline_status = "ok"

    if not rewrite_reachable:
        reason_code = REASON_REWRITE_UNAVAILABLE
        pipeline_status = "degraded"
    elif keys_configured == 0 and undrafted > 0:
        reason_code = REASON_OPENROUTER_NO_KEYS
        pipeline_status = "degraded"
    elif not dispatch_enabled and undrafted > 0:
        reason_code = REASON_DISPATCH_DISABLED
        pipeline_status = "degraded"
    elif not poll_enabled and undrafted == 0 and unconsumed_drafts == 0:
        reason_code = REASON_INGESTION_DISABLED
        pipeline_status = "degraded"
    elif unconsumed_drafts == 0:
        if undrafted > 0 and last_error_code not in (REASON_OK, ""):
            reason_code = last_error_code
            pipeline_status = "degraded"
        elif undrafted > 0 and int(last_dispatch_failed or 0) > 0:
            reason_code = last_error_code if last_error_code != REASON_OK else REASON_PIPELINE_DEGRADED
            pipeline_status = "degraded"
        else:
            reason_code = REASON_QUEUE_EMPTY
            pipeline_status = "ok"
    else:
        reason_code = REASON_OK
        pipeline_status = "ok"

    key_usage = [
        {
            "key_alias": row.key_alias,
            "model": row.model,
            "usage_count": row.usage_count,
            "error_count": row.error_count,
        }
        for row in db.scalars(select(LLMRotationUsage).order_by(LLMRotationUsage.key_alias)).all()
    ]

    last_draft_created_at = db.scalar(select(func.max(Draft.created_at)))

    detail = last_error_message if pipeline_status == "degraded" else None
    return {
        "pipeline_status": pipeline_status,
        "reason_code": reason_code,
        "reason_message": human_reason_message(reason_code, detail=detail),
        "checked_at": datetime.now(UTC).isoformat(),
        "stages": {
            "poll_enabled": poll_enabled,
            "dispatch_enabled": dispatch_enabled,
            "rewrite_reachable": rewrite_reachable,
        },
        "queue": {
            "unconsumed_drafts": unconsumed_drafts,
            "undrafted_in_topic_clusters": undrafted,
            "last_draft_created_at": last_draft_created_at.isoformat() if last_draft_created_at else None,
            "last_dispatch_at": last_dispatch_at,
            "last_dispatch_dispatched": last_dispatch_dispatched,
            "last_dispatch_failed": last_dispatch_failed,
        },
        "openrouter": {
            "keys_configured": keys_configured,
            "last_error_code": last_error_code if last_error_code != REASON_OK else None,
            "last_error_message": last_error_message or None,
            "last_error_at": last_error_at,
            "key_usage": key_usage,
        },
    }


def build_list_meta(db: Session, *, rewrite_channel: grpc.Channel | None, item_count: int) -> dict:
    status = build_pipeline_status(db, rewrite_channel=rewrite_channel)
    if item_count > 0:
        status["reason_code"] = REASON_OK
        status["pipeline_status"] = "ok"
        status["reason_message"] = human_reason_message(REASON_OK)
    return {
        "pipeline_status": status["pipeline_status"],
        "reason_code": status["reason_code"],
        "reason_message": status["reason_message"],
        "checked_at": status["checked_at"],
        "undrafted_in_topic_clusters": status["queue"]["undrafted_in_topic_clusters"],
        "last_draft_created_at": status["queue"]["last_draft_created_at"],
    }
