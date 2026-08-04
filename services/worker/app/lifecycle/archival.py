from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from db.app_settings import get_setting
from db.enums import DraftStatus
from db.models import Draft
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# A draft that's sat in READY_FOR_REVIEW this long without a human
# decision archives itself (ТЗ §4.20, §6.5) — the freshness score
# already decayed it toward the bottom of the queue (Фаза 3); this is
# the promised follow-through ("уходит в архив"), not just lower
# ranking. Return from ARCHIVED is manual (Фаза 6 plan) — no auto-
# unarchive job exists on purpose.
DEFAULT_TTL_HOURS = 72
TTL_HOURS_SETTING_KEY = "queue.ttl_archive_hours"


def run_archival_cycle(db: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    ttl_hours = get_setting(db, TTL_HOURS_SETTING_KEY, DEFAULT_TTL_HOURS)
    cutoff = now - timedelta(hours=ttl_hours)

    stale = db.scalars(
        select(Draft).where(Draft.status == DraftStatus.READY_FOR_REVIEW, Draft.created_at < cutoff)
    ).all()
    for draft in stale:
        draft.status = DraftStatus.ARCHIVED
        logger.info("draft %s archived (TTL %sh exceeded)", draft.id, ttl_hours)
    db.commit()
    return {"archived": len(stale)}
