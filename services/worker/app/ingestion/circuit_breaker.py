from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.app_settings import get_setting
from db.models import Source
from sqlalchemy.orm import Session

# N consecutive failures/garbage responses -> pause the source instead of
# retrying every cycle (ТЗ §4.20). Pause duration is a simple fixed
# backoff — good enough for MVP volume; not per-failure exponential.
# Runtime-editable via AppSetting (ТЗ §4.21) — these are the fallback
# defaults before `circuit_breaker.*` is ever seeded.
CONSECUTIVE_FAILURE_THRESHOLD = 5
FAILURE_THRESHOLD_SETTING_KEY = "circuit_breaker.failure_threshold"
PAUSE_DURATION = timedelta(hours=1)
PAUSE_HOURS_SETTING_KEY = "circuit_breaker.pause_hours"


def record_success(source: Source) -> None:
    now = datetime.now(UTC)
    source.consecutive_failures = 0
    source.paused_until = None
    source.last_success_at = now
    source.last_polled_at = now


def record_failure(db: Session, source: Source) -> None:
    now = datetime.now(UTC)
    source.consecutive_failures += 1
    source.last_polled_at = now
    threshold = get_setting(db, FAILURE_THRESHOLD_SETTING_KEY, CONSECUTIVE_FAILURE_THRESHOLD)
    if source.consecutive_failures >= threshold:
        pause_hours = get_setting(
            db, PAUSE_HOURS_SETTING_KEY, PAUSE_DURATION.total_seconds() / 3600
        )
        source.paused_until = now + timedelta(hours=pause_hours)


def is_paused(source: Source) -> bool:
    return source.paused_until is not None and source.paused_until > datetime.now(UTC)
