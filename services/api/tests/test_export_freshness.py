from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api_app.integrations.freshness import (
    resolve_content_generated_since,
    resolve_export_time_cutoffs,
)


def test_resolve_freshness_today_uses_created_at():
    now = datetime(2026, 9, 2, 15, 30, tzinfo=UTC)
    cutoffs = resolve_export_time_cutoffs(
        freshness="today", generated_since=None, max_age_hours=None, now=now
    )
    assert cutoffs.content_generated_since is None
    assert cutoffs.created_since == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


def test_resolve_freshness_48h_uses_created_at():
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    cutoffs = resolve_export_time_cutoffs(
        freshness="48h", generated_since=None, max_age_hours=None, now=now
    )
    assert cutoffs.content_generated_since is None
    assert cutoffs.created_since == datetime(2026, 8, 31, 15, 0, tzinfo=UTC)


def test_resolve_max_age_hours():
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    cutoff = resolve_content_generated_since(
        freshness=None,
        generated_since=None,
        max_age_hours=24,
        now=now,
    )
    assert cutoff == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_resolve_today_and_generated_since_are_independent():
    now = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    explicit = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
    cutoffs = resolve_export_time_cutoffs(
        generated_since=explicit,
        freshness="today",
        max_age_hours=None,
        now=now,
    )
    assert cutoffs.created_since == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    assert cutoffs.content_generated_since == explicit


def test_resolve_48h_and_max_age_are_independent():
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    cutoffs = resolve_export_time_cutoffs(
        freshness="48h",
        generated_since=None,
        max_age_hours=24,
        now=now,
    )
    assert cutoffs.created_since == datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
    assert cutoffs.content_generated_since == datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
