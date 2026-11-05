from __future__ import annotations

from datetime import UTC, datetime, timedelta

import grpc
from common.generation_hours import (
    generation_allowed,
    generation_hours_as_dict,
    load_generation_hours,
)
from common.grpc_client import check_rewrite_health
from common.integration_reasons import (
    REASON_DISPATCH_DISABLED,
    REASON_DRAFTS_STUCK_DRAFTING,
    REASON_GENERATION_OUTSIDE_HOURS,
    REASON_INGESTION_DISABLED,
    REASON_OK,
    REASON_OPENROUTER_NO_KEYS,
    REASON_PIPELINE_DEGRADED,
    REASON_QUEUE_EMPTY,
    REASON_REWRITE_UNAVAILABLE,
    REASON_WORKER_STALE,
    human_reason_message,
)
from common.llm_token_totals import load_token_totals
from common.pipeline_telemetry import (
    KEY_LAST_DISPATCH_AT,
    KEY_LAST_DISPATCH_DISPATCHED,
    KEY_LAST_DISPATCH_FAILED,
    KEY_LAST_ERROR_AT,
    KEY_LAST_ERROR_CODE,
    KEY_LAST_ERROR_MESSAGE,
    KEY_LAST_WORKER_HEARTBEAT_AT,
)
from db.app_settings import get_setting
from db.enums import DraftStatus, TopicStatus
from db.models import Draft, DraftExportLog, LLMRotationUsage, NewsCluster
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Poll ticks can run >2 min; allow slack before declaring worker dead.
WORKER_STALE_AFTER = timedelta(minutes=5)
# Fresh drafts must leave drafting via compliance within this window.
DRAFTING_STUCK_AFTER = timedelta(minutes=10)


def count_unconsumed_drafts(
    db: Session,
    *,
    statuses: list[str],
) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Draft)
            .outerjoin(DraftExportLog, DraftExportLog.draft_id == Draft.id)
            .where(Draft.status.in_(statuses), DraftExportLog.draft_id.is_(None))
        )
        or 0
    )


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


def _parse_iso(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def count_drafting_drafts(db: Session) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Draft).where(Draft.status == DraftStatus.DRAFTING)
        )
        or 0
    )


def oldest_drafting_age(db: Session, *, now: datetime | None = None) -> timedelta | None:
    oldest = db.scalar(
        select(func.min(Draft.created_at)).where(Draft.status == DraftStatus.DRAFTING)
    )
    if oldest is None:
        return None
    moment = now or datetime.now(UTC)
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    return moment - oldest


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
    hours_config = load_generation_hours(db)
    within_generation_hours = generation_allowed(db)
    rewrite_reachable = _rewrite_reachable(rewrite_channel)
    keys_configured = _openrouter_keys_configured(db)

    last_error_code = str(get_setting(db, KEY_LAST_ERROR_CODE, REASON_OK) or REASON_OK)
    last_error_message = str(get_setting(db, KEY_LAST_ERROR_MESSAGE, "") or "")
    last_error_at = get_setting(db, KEY_LAST_ERROR_AT, None)
    last_dispatch_at = get_setting(db, KEY_LAST_DISPATCH_AT, None)
    last_dispatch_dispatched = get_setting(db, KEY_LAST_DISPATCH_DISPATCHED, 0)
    last_dispatch_failed = get_setting(db, KEY_LAST_DISPATCH_FAILED, 0)
    last_worker_heartbeat_at = get_setting(db, KEY_LAST_WORKER_HEARTBEAT_AT, None)
    drafting_count = count_drafting_drafts(db)
    now = datetime.now(UTC)
    heartbeat_at = _parse_iso(last_worker_heartbeat_at)
    worker_stale = heartbeat_at is not None and (now - heartbeat_at) > WORKER_STALE_AFTER
    # No heartbeat ever after deploy still looks "ok" until worker starts —
    # only flag stale when we previously saw a heartbeat.
    drafting_age = oldest_drafting_age(db, now=now)
    drafting_stuck = (
        drafting_count > 0
        and drafting_age is not None
        and drafting_age > DRAFTING_STUCK_AFTER
        and unconsumed_drafts == 0
    )

    reason_code = REASON_OK
    pipeline_status = "ok"

    if not rewrite_reachable:
        reason_code = REASON_REWRITE_UNAVAILABLE
        pipeline_status = "degraded"
    elif worker_stale:
        reason_code = REASON_WORKER_STALE
        pipeline_status = "degraded"
    elif drafting_stuck:
        reason_code = REASON_DRAFTS_STUCK_DRAFTING
        pipeline_status = "degraded"
    elif keys_configured == 0 and undrafted > 0:
        reason_code = REASON_OPENROUTER_NO_KEYS
        pipeline_status = "degraded"
    elif not within_generation_hours and undrafted > 0 and unconsumed_drafts == 0:
        # Intentional pause (nights/weekends) — not an incident for VPS cron.
        reason_code = REASON_GENERATION_OUTSIDE_HOURS
        pipeline_status = "ok"
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
            reason_code = (
                last_error_code if last_error_code != REASON_OK else REASON_PIPELINE_DEGRADED
            )
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
            "within_generation_hours": within_generation_hours,
            "rewrite_reachable": rewrite_reachable,
        },
        "generation_hours": generation_hours_as_dict(hours_config, db=db),
        "queue": {
            "unconsumed_drafts": unconsumed_drafts,
            "undrafted_in_topic_clusters": undrafted,
            "drafting_drafts": drafting_count,
            "last_draft_created_at": last_draft_created_at.isoformat()
            if last_draft_created_at
            else None,
            "last_dispatch_at": last_dispatch_at,
            "last_dispatch_dispatched": last_dispatch_dispatched,
            "last_dispatch_failed": last_dispatch_failed,
            "last_worker_heartbeat_at": last_worker_heartbeat_at,
            "worker_stale": worker_stale,
        },
        "openrouter": {
            "keys_configured": keys_configured,
            "last_error_code": last_error_code if last_error_code != REASON_OK else None,
            "last_error_message": last_error_message or None,
            "last_error_at": last_error_at,
            "key_usage": key_usage,
        },
        "llm_tokens": load_token_totals(db),
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
        "drafting_drafts": status["queue"]["drafting_drafts"],
        "last_draft_created_at": status["queue"]["last_draft_created_at"],
        "last_worker_heartbeat_at": status["queue"]["last_worker_heartbeat_at"],
        "worker_stale": status["queue"]["worker_stale"],
        "llm_tokens": status["llm_tokens"],
    }
