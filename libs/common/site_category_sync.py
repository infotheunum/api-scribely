from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.theunum_categories_client import TheunumCategoryRecord, fetch_theunum_categories
from db.app_settings import get_setting, set_setting
from db.enums import TagCategoryKind
from db.models import TagCategoryCache
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

LAST_SYNC_KEY = "theunum.categories_last_sync_at"
LAST_SYNC_ERROR_KEY = "theunum.categories_last_sync_error"
SYNC_INTERVAL_SECONDS_KEY = "theunum.categories_sync_interval_seconds"

DEFAULT_SYNC_INTERVAL_SECONDS = 86400  # 24h


def upsert_theunum_categories(db: Session, records: list[TheunumCategoryRecord]) -> dict:
    """Upsert active categories; deactivate local rows missing from payload."""
    seen_slugs: set[str] = set()
    created, updated = 0, 0

    for record in records:
        seen_slugs.add(record.slug)
        row = db.scalar(
            select(TagCategoryCache).where(
                TagCategoryCache.kind == TagCategoryKind.CATEGORY,
                TagCategoryCache.slug == record.slug,
            )
        )
        if row is None:
            db.add(
                TagCategoryCache(
                    id=record.id,
                    kind=TagCategoryKind.CATEGORY,
                    slug=record.slug,
                    name_en=record.name_en,
                    name_ru=record.name_ru,
                    is_active=True,
                )
            )
            created += 1
            continue

        changed = False
        if row.id != record.id:
            row.id = record.id
            changed = True
        if row.name_en != record.name_en:
            row.name_en = record.name_en
            changed = True
        if row.name_ru != record.name_ru:
            row.name_ru = record.name_ru
            changed = True
        if not row.is_active:
            row.is_active = True
            changed = True
        if changed:
            updated += 1

    deactivated = 0
    for row in db.scalars(
        select(TagCategoryCache).where(TagCategoryCache.kind == TagCategoryKind.CATEGORY)
    ).all():
        if row.slug not in seen_slugs and row.is_active:
            row.is_active = False
            deactivated += 1

    return {
        "fetched": len(records),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
    }


def sync_theunum_categories_from_api(
    db: Session,
    *,
    base_url: str,
    path: str,
    api_token: str,
) -> dict:
    if not base_url.strip():
        raise RuntimeError("THEUNUM_API_BASE_URL is not configured")
    if not api_token.strip():
        # Публичный GET /api/v1/categories?locale=… — token опционален.
        logger.warning("THEUNUM_API_TOKEN empty — fetching categories without Authorization")

    records = fetch_theunum_categories(base_url=base_url, path=path, api_token=api_token)
    if not records:
        raise RuntimeError("theunum categories API returned empty list")

    stats = upsert_theunum_categories(db, records)
    now = datetime.now(UTC).isoformat()
    set_setting(db, LAST_SYNC_KEY, now)
    set_setting(db, LAST_SYNC_ERROR_KEY, "")
    stats["synced_at"] = now
    return stats


def run_theunum_categories_sync(
    db: Session,
    *,
    base_url: str,
    path: str,
    api_token: str,
) -> dict:
    try:
        return sync_theunum_categories_from_api(
            db,
            base_url=base_url,
            path=path,
            api_token=api_token,
        )
    except Exception as exc:
        set_setting(db, LAST_SYNC_ERROR_KEY, str(exc))
        raise exc


def categories_sync_due(db: Session, *, interval_seconds: int | None = None) -> bool:
    interval = interval_seconds
    if interval is None:
        interval = int(get_setting(db, SYNC_INTERVAL_SECONDS_KEY, DEFAULT_SYNC_INTERVAL_SECONDS))
    last_raw = get_setting(db, LAST_SYNC_KEY, None)
    if not last_raw:
        return True
    try:
        last = datetime.fromisoformat(str(last_raw))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - last).total_seconds()
    return elapsed >= interval
