from __future__ import annotations

import logging
import os

from common.settings import CommonSettings
from common.site_category_sync import (
    categories_sync_due,
    run_theunum_categories_sync,
)
from db.app_settings import get_setting
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SYNC_ENABLED_KEY = "pipeline.theunum_categories_sync_enabled"


def _resolved_token(settings: CommonSettings) -> str:
    return settings.theunum_api_token.strip() or os.environ.get("THEUNUM_INTEGRATION_TOKEN", "")


def run_theunum_categories_sync_if_due(db: Session, settings: CommonSettings) -> dict | None:
    if not get_setting(db, SYNC_ENABLED_KEY, True):
        return None
    if not categories_sync_due(db):
        return None
    stats = run_theunum_categories_sync(
        db,
        base_url=settings.theunum_api_base_url,
        path=settings.theunum_categories_path,
        api_token=_resolved_token(settings),
    )
    db.commit()
    logger.info("theunum categories synced: %s", stats)
    return stats
