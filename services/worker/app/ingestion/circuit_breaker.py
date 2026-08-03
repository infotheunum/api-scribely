from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.models import Source

# N consecutive failures/garbage responses -> pause the source instead of
# retrying every cycle (ТЗ §4.20). Pause duration is a simple fixed
# backoff — good enough for MVP volume; not per-failure exponential.
CONSECUTIVE_FAILURE_THRESHOLD = 5
PAUSE_DURATION = timedelta(hours=1)


def record_success(source: Source) -> None:
    now = datetime.now(UTC)
    source.consecutive_failures = 0
    source.paused_until = None
    source.last_success_at = now
    source.last_polled_at = now


def record_failure(source: Source) -> None:
    now = datetime.now(UTC)
    source.consecutive_failures += 1
    source.last_polled_at = now
    if source.consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
        source.paused_until = now + PAUSE_DURATION


def is_paused(source: Source) -> bool:
    return source.paused_until is not None and source.paused_until > datetime.now(UTC)
