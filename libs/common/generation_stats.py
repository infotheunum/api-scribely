"""Generation funnel stats for Admin dashboard (Фаза 8 lite)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from db.enums import DraftStatus, QuarantineReason
from db.models import AuditLog, ClusterQuarantine, Draft
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.generation_hours import DEFAULT_TIMEZONE, effective_daily_limit, resolve_tz
from common.llm_token_totals import load_token_totals

PeriodLabel = Literal["today", "7d", "30d"]


def resolve_period(
    period: str,
    *,
    now: datetime | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> tuple[datetime, datetime, PeriodLabel]:
    """Return [start, end) UTC bounds for a named period in editorial TZ."""
    tz = resolve_tz(tz_name)
    now = now or datetime.now(UTC)
    local_now = now.astimezone(tz)
    label: PeriodLabel
    if period == "7d":
        label = "7d"
        local_start = (local_now - timedelta(days=6)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "30d":
        label = "30d"
        local_start = (local_now - timedelta(days=29)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        label = "today"
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(UTC)
    end = now if now.tzinfo else now.replace(tzinfo=UTC)
    return start, end, label


def build_generation_stats(
    db: Session,
    *,
    period: str = "today",
    now: datetime | None = None,
) -> dict[str, Any]:
    start, end, label = resolve_period(period, now=now)

    drafts_created = int(
        db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.created_at >= start, Draft.created_at < end)
        )
        or 0
    )

    by_status_rows = db.execute(
        select(Draft.status, func.count())
        .where(Draft.created_at >= start, Draft.created_at < end)
        .group_by(Draft.status)
    ).all()
    drafts_by_status = {str(status): int(count) for status, count in by_status_rows}

    quality_gate_rejected = int(
        db.scalar(
            select(func.count())
            .select_from(ClusterQuarantine)
            .where(
                ClusterQuarantine.created_at >= start,
                ClusterQuarantine.created_at < end,
                ClusterQuarantine.reason == QuarantineReason.FACTUAL_VERIFICATION_FAILED,
            )
        )
        or 0
    )

    quarantine_rows = db.execute(
        select(ClusterQuarantine.reason, func.count())
        .where(
            ClusterQuarantine.created_at >= start,
            ClusterQuarantine.created_at < end,
        )
        .group_by(ClusterQuarantine.reason)
    ).all()
    quarantine_by_reason = {str(reason): int(count) for reason, count in quarantine_rows}

    editor_published = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "publish",
                AuditLog.entity_type == "Draft",
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
        )
        or 0
    )
    editor_rejected = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "reject",
                AuditLog.entity_type == "Draft",
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
        )
        or 0
    )
    editor_needs_fix = int(
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "needs_fix",
                AuditLog.entity_type == "Draft",
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
        )
        or 0
    )

    # Current queue snapshot (not period-scoped): what editors see now.
    queue_ready = int(
        db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.status == DraftStatus.READY_FOR_REVIEW)
        )
        or 0
    )
    queue_needs_fix = int(
        db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(Draft.status == DraftStatus.NEEDS_FIX)
        )
        or 0
    )

    tokens = load_token_totals(db)
    daily_limit = effective_daily_limit(db)

    attempted = drafts_created + quality_gate_rejected
    return {
        "period": {
            "label": label,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
        "funnel": {
            "attempted_rewrite": attempted,
            "drafts_created": drafts_created,
            "quality_gate_rejected": quality_gate_rejected,
            "editor_published": editor_published,
            "editor_rejected": editor_rejected,
            "editor_needs_fix": editor_needs_fix,
        },
        "drafts_by_status": drafts_by_status,
        "quarantine_by_reason": quarantine_by_reason,
        "queue_now": {
            "ready_for_review": queue_ready,
            "needs_fix": queue_needs_fix,
        },
        "llm_tokens": tokens,
        "targets": {
            "weekday_kpi_band": [140, 160],
            "effective_daily_limit": daily_limit,
        },
    }
