from __future__ import annotations

import json

import pytest
from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.rewrite.orchestrator import rewrite_cluster
from rewrite_app.settings import RewriteSettings

VALID_RESULT = {
    "title_en": "Bitcoin Surges Past $120,000 as ETF Inflows Accelerate",
    "body_en": "x" * 200,
    "title_ru": "Биткоин превысил $120,000 на фоне роста притоков в ETF",
    "body_ru": "y" * 200,
    "title_en_variants": [],
    "title_ru_variants": [],
    "sponsor_flag": False,
    "press_release_flag": False,
    "disclaimer_flag": True,
    "suggested_category_slug": "bitcoin",
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


def test_rewrite_cluster_parses_valid_response(clean_db, prompt_version, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(VALID_RESULT), "key_1", "openai/gpt-oss-20b:free"),
    )

    result, key_alias, model = rewrite_cluster(
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


def test_rewrite_cluster_rejects_too_short_body(clean_db, prompt_version, monkeypatch):
    bad = dict(VALID_RESULT, body_en="too short")
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(bad), "key_1", "m"),
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
