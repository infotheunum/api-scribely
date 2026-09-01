from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from api_app.integrations.freshness import resolve_content_generated_since


def test_resolve_freshness_today():
    now = datetime(2026, 9, 2, 15, 30, tzinfo=UTC)
    cutoff = resolve_content_generated_since(freshness="today", generated_since=None, max_age_hours=None, now=now)
    assert cutoff == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


def test_resolve_freshness_48h():
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
    cutoff = resolve_content_generated_since(freshness="48h", generated_since=None, max_age_hours=None, now=now)
    assert cutoff == datetime(2026, 8, 31, 15, 0, tzinfo=UTC)


def test_resolve_max_age_hours():
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    cutoff = resolve_content_generated_since(
        freshness=None,
        generated_since=None,
        max_age_hours=24,
        now=now,
    )
    assert cutoff == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_resolve_uses_most_recent_cutoff():
    now = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    explicit = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
    cutoff = resolve_content_generated_since(
        generated_since=explicit,
        freshness="today",
        max_age_hours=None,
        now=now,
    )
    assert cutoff == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
