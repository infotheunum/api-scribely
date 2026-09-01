from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CATEGORY_LOCALES: tuple[str, ...] = ("en", "ru")


@dataclass(frozen=True)
class TheunumCategoryRecord:
    id: str
    slug: str
    name_en: str | None
    name_ru: str | None


def _parse_category_item(raw: dict, *, locale: str) -> TheunumCategoryRecord | None:
    category_id = raw.get("id") or raw.get("categoryId")
    slug = raw.get("slug")
    if not category_id or not slug:
        return None

    name_en = raw.get("nameEn") or raw.get("name_en")
    name_ru = raw.get("nameRu") or raw.get("name_ru")
    localized = raw.get("name") or raw.get("title") or raw.get("label")

    if locale == "en" and not name_en and localized:
        name_en = localized
    if locale == "ru" and not name_ru and localized:
        name_ru = localized

    return TheunumCategoryRecord(
        id=str(category_id),
        slug=str(slug).strip().lower(),
        name_en=str(name_en).strip() if name_en else None,
        name_ru=str(name_ru).strip() if name_ru else None,
    )


def _extract_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "categories"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _merge_records(
    merged: dict[str, TheunumCategoryRecord],
    record: TheunumCategoryRecord,
) -> None:
    existing = merged.get(record.slug)
    if existing is None:
        merged[record.slug] = record
        return
    merged[record.slug] = TheunumCategoryRecord(
        id=record.id or existing.id,
        slug=record.slug,
        name_en=record.name_en or existing.name_en,
        name_ru=record.name_ru or existing.name_ru,
    )


def fetch_theunum_categories(
    *,
    base_url: str,
    path: str,
    api_token: str = "",
    locales: tuple[str, ...] = DEFAULT_CATEGORY_LOCALES,
    timeout: float = 30.0,
) -> list[TheunumCategoryRecord]:
    """GET categories from api.theunum.io for each locale and merge names.

    Live API (theunum):
      GET /api/v1/categories?locale=en
      GET /api/v1/categories?locale=ru

    ``path`` — только путь без query, default ``/api/v1/categories``.
    """
    merged: dict[str, TheunumCategoryRecord] = {}
    headers = {"Accept": "application/json"}
    if api_token.strip():
        headers["Authorization"] = f"Bearer {api_token.strip()}"

    base = base_url.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"

    for locale in locales:
        query = urlencode({"locale": locale})
        url = f"{base}{normalized_path}?{query}"
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        items = _extract_items(response.json())
        for item in items:
            record = _parse_category_item(item, locale=locale)
            if record is not None:
                _merge_records(merged, record)
        logger.info("fetched %d category rows from theunum %s", len(items), url)

    records = list(merged.values())
    logger.info("merged %d unique categories from locales %s", len(records), locales)
    return records
