from __future__ import annotations

from common.integration_export_settings import (
    DEFAULT_LIMIT_KEY,
    merge_export_limit_query,
)
from db.app_settings import set_setting


def test_merge_limit_uses_admin_default(clean_db):
    set_setting(clean_db, DEFAULT_LIMIT_KEY, 100)
    clean_db.commit()

    limit, source = merge_export_limit_query(clean_db, limit=None)
    assert limit == 100
    assert source == "admin_default"


def test_merge_limit_prefers_query(clean_db):
    set_setting(clean_db, DEFAULT_LIMIT_KEY, 100)
    clean_db.commit()

    limit, source = merge_export_limit_query(clean_db, limit=25)
    assert limit == 25
    assert source == "query"


def test_merge_limit_api_default(clean_db):
    limit, source = merge_export_limit_query(clean_db, limit=None)
    assert limit == 50
    assert source == "api_default"
