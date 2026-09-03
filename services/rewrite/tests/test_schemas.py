from __future__ import annotations

from rewrite_app.prompt.style_guide import BODY_MIN_CHARS
from rewrite_app.rewrite.schemas import RewriteResultSchema


def _base_payload(**overrides):
    payload = {
        "title_en": "Bitcoin Surges Past $120,000 as ETF Inflows Accelerate",
        "body_en": "x" * BODY_MIN_CHARS,
        "title_ru": "Биткоин превысил $120,000 на фоне роста притоков в ETF",
        "body_ru": "y" * BODY_MIN_CHARS,
        "title_en_variants": [],
        "title_ru_variants": [],
        "sponsor_flag": False,
        "press_release_flag": False,
        "disclaimer_flag": True,
        "suggested_category_slug": "crypto",
        "tags": [{"slug": "etf", "name": "ETF"}],
        "seo_en": {
            "seo_title": "t",
            "seo_description": "d",
            "slug": "s",
            "og_title": "o",
            "og_description": "od",
            "focus_keyphrase": "bitcoin etf",
            "keywords": ["bitcoin"],
        },
        "seo_ru": {
            "seo_title": "t",
            "seo_description": "d",
            "slug": "s",
            "og_title": "o",
            "og_description": "od",
            "focus_keyphrase": "биткоин etf",
            "keywords": ["биткоин"],
        },
        "image_brief": {
            "image_brief": "b",
            "image_mood": "neutral",
            "image_subjects": ["bitcoin"],
            "image_style": "photo",
            "image_do_not": [],
            "image_alt": "a",
            "image_caption": "c",
            "image_source_suggestion": "s",
        },
    }
    payload.update(overrides)
    return payload


def test_schema_normalizes_three_paragraph_bodies():
    body = "Lead paragraph.\n\nMiddle paragraph.\n\nClosing paragraph."
    result = RewriteResultSchema.model_validate(_base_payload(body_en=body, body_ru=body))
    assert result.body_en.count("\n\n") == 2
    assert result.body_ru.count("\n\n") == 2


def test_schema_normalizes_unicode_spaces_in_titles():
    title = "Lazarus moved $30\u202fмлн through Hyperliquid"
    result = RewriteResultSchema.model_validate(
        _base_payload(title_en=title, title_ru=title)
    )
    assert "\u202f" not in result.title_en
    assert result.title_en == "Lazarus moved $30 млн through Hyperliquid"
    assert result.title_ru == result.title_en
