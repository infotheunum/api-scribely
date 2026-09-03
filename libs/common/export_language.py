"""Apply Export API language projection onto draft payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ExportLanguage = Literal["ru", "en", "all"]


def output_locales_to_export_language(locales: list[str] | tuple[str, ...]) -> ExportLanguage:
    """Map rewrite.output_locales to Export API language projection."""
    ordered = [code for code in ("ru", "en") if code in locales]
    if len(ordered) == 1:
        return ordered[0]  # type: ignore[return-value]
    return "all"


def parse_export_language(raw: str | None) -> ExportLanguage | None:
    if raw in ("ru", "en", "all"):
        return raw  # type: ignore[return-value]
    return None


def resolve_export_language(db: Session, raw: str | None) -> ExportLanguage:
    """Explicit query wins; otherwise follow rewrite.output_locales (default ru-only)."""
    explicit = parse_export_language(raw)
    if explicit is not None:
        return explicit
    from common.rewrite_output_locales import get_output_locales

    return output_locales_to_export_language(get_output_locales(db))


def project_export_item(item: dict[str, Any], language: ExportLanguage) -> dict[str, Any]:
    """Keep contract fields; blank out the inactive locale when language is ru/en."""
    if language == "all":
        return item
    data = dict(item)
    if language == "ru":
        data["title_en"] = ""
        data["body_en"] = ""
        data["body_en_html"] = ""
        data["title_en_variants"] = []
        data["seo_title_en"] = None
        data["seo_description_en"] = None
        data["slug_en"] = None
        data["og_title_en"] = None
        data["og_description_en"] = None
        data["focus_keyphrase_en"] = None
        data["keywords_en"] = []
    elif language == "en":
        data["title_ru"] = ""
        data["body_ru"] = ""
        data["body_ru_html"] = ""
        data["title_ru_variants"] = []
        data["seo_title_ru"] = None
        data["seo_description_ru"] = None
        data["slug_ru"] = None
        data["og_title_ru"] = None
        data["og_description_ru"] = None
        data["focus_keyphrase_ru"] = None
        data["keywords_ru"] = []
    return data
