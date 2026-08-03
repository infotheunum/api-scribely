from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.enums import SourceTier, SourceType
from db.models import Source
from worker_app.ingestion.circuit_breaker import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    is_paused,
    record_failure,
    record_success,
)


def _source() -> Source:
    # consecutive_failures defaults to 0 only once SQLAlchemy actually
    # flushes/loads the row — a bare in-memory Source() has it as None,
    # unlike every real Source these functions ever see in production.
    return Source(
        name="Test Source",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
        consecutive_failures=0,
    )


def test_record_success_resets_failures():
    source = _source()
    source.consecutive_failures = 3
    source.paused_until = datetime.now(UTC) + timedelta(hours=1)

    record_success(source)

    assert source.consecutive_failures == 0
    assert source.paused_until is None
    assert source.last_success_at is not None
    assert source.last_polled_at is not None


def test_repeated_failures_trip_breaker():
    source = _source()
    for _ in range(CONSECUTIVE_FAILURE_THRESHOLD - 1):
        record_failure(source)
        assert not is_paused(source)

    record_failure(source)
    assert source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD
    assert is_paused(source)


def test_paused_source_reports_paused_until_expiry():
    source = _source()
    source.paused_until = datetime.now(UTC) - timedelta(minutes=1)
    assert not is_paused(source)

    source.paused_until = datetime.now(UTC) + timedelta(minutes=1)
    assert is_paused(source)
