"""Admin-configurable locales for rewrite output (EN / RU)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from db.app_settings import get_setting, set_setting
from sqlalchemy.orm import Session

OutputLocale = Literal["en", "ru"]
ALLOWED_LOCALES: frozenset[str] = frozenset({"en", "ru"})
DEFAULT_OUTPUT_LOCALES: tuple[OutputLocale, ...] = ("ru",)

OUTPUT_LOCALES_KEY = "rewrite.output_locales"
OUTPUT_LOCALES_DESCRIPTION = (
    "Locales to generate in Rewrite Orchestrator — JSON array of en/ru. "
    "Default [\"ru\"]. Later can be [\"ru\",\"en\"]."
)

EMPTY_SEO = {
    "seo_title": "",
    "seo_description": "",
    "slug": "",
    "og_title": "",
    "og_description": "",
    "focus_keyphrase": "",
    "keywords": [],
}


def parse_output_locales(raw: Any) -> list[OutputLocale]:
    """Normalize AppSetting / form value to a non-empty en/ru list (default ru)."""
    if raw is None or raw == "":
        return list(DEFAULT_OUTPUT_LOCALES)
    values: list[str]
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("["):
            import json

            try:
                parsed = json.loads(cleaned)
            except ValueError:
                return list(DEFAULT_OUTPUT_LOCALES)
            if not isinstance(parsed, list):
                return list(DEFAULT_OUTPUT_LOCALES)
            values = [str(item).strip().lower() for item in parsed]
        else:
            values = [part.strip().lower() for part in cleaned.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        values = [str(item).strip().lower() for item in raw]
    else:
        return list(DEFAULT_OUTPUT_LOCALES)

    ordered: list[OutputLocale] = []
    for locale in ("ru", "en"):
        if locale in values and locale not in ordered:
            ordered.append(locale)  # type: ignore[arg-type]
    for value in values:
        if value in ALLOWED_LOCALES and value not in ordered:
            ordered.append(value)  # type: ignore[arg-type]
    return ordered or list(DEFAULT_OUTPUT_LOCALES)


def get_output_locales(db: Session) -> list[OutputLocale]:
    return parse_output_locales(get_setting(db, OUTPUT_LOCALES_KEY, list(DEFAULT_OUTPUT_LOCALES)))


def set_output_locales(
    db: Session,
    locales: list[str] | tuple[str, ...] | str,
    *,
    updated_by: uuid.UUID | None = None,
) -> list[OutputLocale]:
    normalized = parse_output_locales(locales)
    set_setting(
        db,
        OUTPUT_LOCALES_KEY,
        list(normalized),
        description=OUTPUT_LOCALES_DESCRIPTION,
        updated_by=updated_by,
    )
    return normalized


def locale_enabled(locales: list[str] | tuple[str, ...], code: str) -> bool:
    return code in locales


def fill_inactive_locale_fields(payload: dict[str, Any], locales: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Ensure inactive locale fields are empty so validation can skip them."""
    data = dict(payload)
    if not locale_enabled(locales, "en"):
        data["title_en"] = ""
        data["body_en"] = ""
        data["title_en_variants"] = []
        data["seo_en"] = dict(EMPTY_SEO)
    if not locale_enabled(locales, "ru"):
        data["title_ru"] = ""
        data["body_ru"] = ""
        data["title_ru_variants"] = []
        data["seo_ru"] = dict(EMPTY_SEO)
    return data
