from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.site_categories import (
    STATIC_SLUG_ALIASES,
    _normalize_slug,
    _static_aliases_for_canonical,
    reconcile_draft_category_slugs,
)
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


def _merge_aliases(existing: list[str] | None, *extra: str) -> list[str]:
    merged = {_normalize_slug(item) for item in (existing or []) if _normalize_slug(item)}
    for item in extra:
        normalized = _normalize_slug(item)
        if normalized:
            merged.add(normalized)
    return sorted(merged)


def _upsert_category_row(db: Session, record: TheunumCategoryRecord) -> tuple[str, bool]:
    """Upsert by CMS id; merge slug renames into aliases. Returns action, changed."""
    row_by_id = db.scalar(
        select(TagCategoryCache).where(
            TagCategoryCache.kind == TagCategoryKind.CATEGORY,
            TagCategoryCache.id == record.id,
        )
    )
    static_aliases = _static_aliases_for_canonical(record.slug)

    if row_by_id is not None:
        changed = False
        if row_by_id.slug != record.slug:
            logger.info(
                "category id=%s slug renamed locally %s → %s",
                record.id,
                row_by_id.slug,
                record.slug,
            )
            row_by_id.aliases = _merge_aliases(row_by_id.aliases, row_by_id.slug, *static_aliases)
            row_by_id.slug = record.slug
            changed = True
        else:
            merged_aliases = _merge_aliases(row_by_id.aliases, *static_aliases)
            if merged_aliases != (row_by_id.aliases or []):
                row_by_id.aliases = merged_aliases
                changed = True

        if row_by_id.name_en != record.name_en:
            row_by_id.name_en = record.name_en
            changed = True
        if row_by_id.name_ru != record.name_ru:
            row_by_id.name_ru = record.name_ru
            changed = True
        if not row_by_id.is_active:
            row_by_id.is_active = True
            changed = True
        return ("updated" if changed else "unchanged", changed)

    row_by_slug = db.scalar(
        select(TagCategoryCache).where(
            TagCategoryCache.kind == TagCategoryKind.CATEGORY,
            TagCategoryCache.slug == record.slug,
        )
    )
    if row_by_slug is not None:
        changed = False
        if row_by_slug.id != record.id:
            row_by_slug.id = record.id
            changed = True
        merged_aliases = _merge_aliases(row_by_slug.aliases, *static_aliases)
        if merged_aliases != (row_by_slug.aliases or []):
            row_by_slug.aliases = merged_aliases
            changed = True
        if row_by_slug.name_en != record.name_en:
            row_by_slug.name_en = record.name_en
            changed = True
        if row_by_slug.name_ru != record.name_ru:
            row_by_slug.name_ru = record.name_ru
            changed = True
        if not row_by_slug.is_active:
            row_by_slug.is_active = True
            changed = True
        return ("updated" if changed else "unchanged", changed)

    db.add(
        TagCategoryCache(
            id=record.id,
            kind=TagCategoryKind.CATEGORY,
            slug=record.slug,
            name_en=record.name_en,
            name_ru=record.name_ru,
            aliases=_merge_aliases([], *static_aliases),
            is_active=True,
        )
    )
    return ("created", True)


def _deactivate_obsolete_category_rows(db: Session, seen_slugs: set[str]) -> int:
    """Deactivate CMS rows missing from API and legacy duplicate slug rows."""
    deactivated = 0
    canonical_targets = set(seen_slugs)

    for row in db.scalars(
        select(TagCategoryCache).where(TagCategoryCache.kind == TagCategoryKind.CATEGORY)
    ).all():
        if not row.is_active:
            continue

        if row.slug not in seen_slugs:
            # Legacy bootstrap row (e.g. cryptocurrency) superseded by crypto from API.
            alias_target = STATIC_SLUG_ALIASES.get(row.slug)
            if alias_target in canonical_targets:
                logger.info(
                    "deactivating legacy category slug=%s (superseded by %s)",
                    row.slug,
                    alias_target,
                )
                row.is_active = False
                deactivated += 1
                continue

            row.is_active = False
            deactivated += 1

    return deactivated


def upsert_theunum_categories(db: Session, records: list[TheunumCategoryRecord]) -> dict:
    """Upsert active categories from API; deactivate obsolete / duplicate rows."""
    seen_slugs: set[str] = set()
    created, updated = 0, 0

    for record in records:
        seen_slugs.add(record.slug)
        action, changed = _upsert_category_row(db, record)
        if action == "created":
            created += 1
        elif changed:
            updated += 1

    deactivated = _deactivate_obsolete_category_rows(db, seen_slugs)
    draft_stats = reconcile_draft_category_slugs(db)

    return {
        "fetched": len(records),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        **draft_stats,
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
