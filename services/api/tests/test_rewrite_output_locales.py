from __future__ import annotations

from common.export_language import parse_export_language, project_export_item
from common.rewrite_output_locales import parse_output_locales, set_output_locales


def test_parse_output_locales_default_ru():
    assert parse_output_locales(None) == ["ru"]
    assert parse_output_locales([]) == ["ru"]
    assert parse_output_locales("") == ["ru"]


def test_parse_output_locales_both():
    assert parse_output_locales(["en", "ru"]) == ["ru", "en"]
    assert parse_output_locales('["ru","en"]') == ["ru", "en"]


def test_set_output_locales_roundtrip(clean_db):
    assert set_output_locales(clean_db, ["en"]) == ["en"]
    clean_db.commit()
    from common.rewrite_output_locales import get_output_locales

    assert get_output_locales(clean_db) == ["en"]


def test_project_export_item_language_ru_blanks_en():
    item = {
        "title_en": "EN",
        "body_en": "body en",
        "body_en_html": "<p>en</p>",
        "title_ru": "RU",
        "body_ru": "body ru",
        "body_ru_html": "<p>ru</p>",
        "title_en_variants": ["a"],
        "keywords_en": ["x"],
    }
    out = project_export_item(item, "ru")
    assert out["title_en"] == ""
    assert out["body_en"] == ""
    assert out["body_en_html"] == ""
    assert out["title_ru"] == "RU"
    assert parse_export_language("ru") == "ru"
    assert parse_export_language("nope") == "all"
