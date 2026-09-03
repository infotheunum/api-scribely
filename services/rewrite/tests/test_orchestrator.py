from __future__ import annotations

import json

import pytest
from common.rewrite_output_locales import set_output_locales
from common.token_usage import TokenUsage
from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import BODY_MAX_CHARS, BODY_MIN_CHARS
from rewrite_app.rewrite.orchestrator import rewrite_cluster
from rewrite_app.settings import RewriteSettings

_USAGE = TokenUsage(9, 8, 17)

VALID_BODY_EN = "x" * BODY_MIN_CHARS
VALID_BODY_RU = "y" * BODY_MIN_CHARS

VALID_RESULT = {
    "title_en": "Bitcoin Surges Past $120,000 as ETF Inflows Accelerate",
    "body_en": VALID_BODY_EN,
    "title_ru": "Биткоин превысил $120,000 на фоне роста притоков в ETF",
    "body_ru": VALID_BODY_RU,
    "title_en_variants": [],
    "title_ru_variants": [],
    "sponsor_flag": False,
    "press_release_flag": False,
    "disclaimer_flag": True,
    "suggested_category_slug": "cryptocurrency",
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


@pytest.fixture
def prompt_version(clean_db) -> PromptVersion:
    version = PromptVersion(template="system prompt", status=PromptVersionStatus.ACTIVE)
    clean_db.add(version)
    clean_db.commit()
    clean_db.refresh(version)
    return version


def _enable_both_locales(clean_db) -> None:
    set_output_locales(clean_db, ["en", "ru"])
    clean_db.commit()


def test_rewrite_cluster_parses_valid_response(clean_db, prompt_version, monkeypatch):
    _enable_both_locales(clean_db)
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(VALID_RESULT), "key_1", "openai/gpt-oss-20b:free", _USAGE),
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block",
        lambda db: "",
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )

    result, key_alias, model, usage = rewrite_cluster(
        clean_db,
        RewriteSettings(),
        prompt_version,
        sources_text="s",
        facts_text="f",
        flags_text="fl",
    )

    assert result.title_en == VALID_RESULT["title_en"]
    assert result.disclaimer_flag is True
    assert len(result.tags) == 1
    assert model == "openai/gpt-oss-20b:free"
    assert usage.total_tokens == 17


def test_rewrite_cluster_ru_only_clears_en(clean_db, prompt_version, monkeypatch):
    set_output_locales(clean_db, ["ru"])
    clean_db.commit()
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(VALID_RESULT), "key_1", "openai/gpt-oss-20b:free", _USAGE),
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block",
        lambda db: "",
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )

    result, *_ = rewrite_cluster(
        clean_db,
        RewriteSettings(),
        prompt_version,
        sources_text="s",
        facts_text="f",
        flags_text="fl",
    )
    assert result.title_en == ""
    assert result.body_en == ""
    assert result.title_ru == VALID_RESULT["title_ru"]


def test_rewrite_cluster_rejects_too_long_body(clean_db, prompt_version, monkeypatch):
    _enable_both_locales(clean_db)
    bad = dict(VALID_RESULT, body_en="x" * (BODY_MAX_CHARS + 1))
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(bad), "key_1", "m", _USAGE),
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block",
        lambda db: "",
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )
    with pytest.raises(RuntimeError, match="failed after"):
        rewrite_cluster(
            clean_db,
            RewriteSettings(),
            prompt_version,
            sources_text="s",
            facts_text="f",
            flags_text="fl",
        )


def test_rewrite_cluster_rejects_too_short_body(clean_db, prompt_version, monkeypatch):
    _enable_both_locales(clean_db)
    bad = dict(VALID_RESULT, body_en="too short")
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(bad), "key_1", "m", _USAGE),
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block",
        lambda db: "",
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )
    with pytest.raises(RuntimeError, match="failed after"):
        rewrite_cluster(
            clean_db,
            RewriteSettings(),
            prompt_version,
            sources_text="s",
            facts_text="f",
            flags_text="fl",
        )
