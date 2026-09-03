"""Apply Export API language projection onto draft payloads."""

from __future__ import annotations

from typing import Any, Literal

ExportLanguage = Literal["ru", "en", "all"]


def parse_export_language(raw: str | None) -> ExportLanguage:
    if raw in ("ru", "en", "all"):
        return raw  # type: ignore[return-value]
    return "all"


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
