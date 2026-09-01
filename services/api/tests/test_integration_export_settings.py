from __future__ import annotations

from datetime import UTC, datetime, timedelta

from common.integration_export_settings import (
    DEFAULT_FRESHNESS_KEY,
    DEFAULT_MAX_AGE_HOURS_KEY,
    merge_export_freshness_query,
)
from db.app_settings import set_setting


def test_merge_uses_admin_default_when_query_empty(clean_db):
    set_setting(clean_db, DEFAULT_FRESHNESS_KEY, "today")
    clean_db.commit()

    gen, fresh, hours, source = merge_export_freshness_query(
        clean_db,
        generated_since=None,
        freshness=None,
        max_age_hours=None,
    )
    assert source == "admin_default"
    assert fresh == "today"
    assert hours is None
    assert gen is None


def test_merge_prefers_explicit_query_over_admin(clean_db):
    set_setting(clean_db, DEFAULT_FRESHNESS_KEY, "today")
    clean_db.commit()

    _, fresh, _, source = merge_export_freshness_query(
        clean_db,
        generated_since=None,
        freshness="48h",
        max_age_hours=None,
    )
    assert source == "query"
    assert fresh == "48h"


def test_merge_admin_max_age_hours(clean_db):
    set_setting(clean_db, DEFAULT_MAX_AGE_HOURS_KEY, 24)
    clean_db.commit()

    _, fresh, hours, source = merge_export_freshness_query(
        clean_db,
        generated_since=None,
        freshness=None,
        max_age_hours=None,
    )
    assert source == "admin_default"
    assert fresh is None
    assert hours == 24
