from __future__ import annotations

import json

import pytest
from common.rewrite_output_locales import set_output_locales
from common.token_usage import TokenUsage
from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import BODY_MIN_CHARS, BODY_SOFT_MAX_CHARS
from rewrite_app.rewrite.orchestrator import (
    _body_length_profile,
    _quality_required_facts,
    rewrite_cluster,
)
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


@pytest.mark.parametrize(
    ("source_chars", "expected"),
    [
        (2200, (2000, 3200)),
        (3000, (2400, 3600)),
        (5000, (2400, 3600)),
        (5001, (3000, 4500)),
    ],
)
def test_body_length_profile_scales_with_source_volume(source_chars, expected):
    profile = _body_length_profile("x" * source_chars)

    assert (profile.target_min, profile.target_max) == expected
    assert profile.source_chars == source_chars


def test_quality_required_facts_keeps_critical_kinds_within_review_budget():
    facts = "\n".join(
        [
            "- [number] 100 долларов",
            "- [what] Компания открыла рынок",
            "- [quote] Цитата руководителя",
            "- [number] 200 долларов",
            "- [essence] Компания открыла новый рынок для клиентов",
            "- [when] 14 сентября",
            "- [who] Руководитель компании",
            "- [number] 300 долларов",
        ]
    )

    selected = _quality_required_facts(facts).splitlines()

    assert len(selected) == 4
    assert selected[0] == "- [essence] Компания открыла новый рынок для клиентов"
    assert "- [number] 100 долларов" in selected
    assert "- [when] 14 сентября" in selected


def test_rewrite_cluster_includes_source_proportional_target(
    clean_db, prompt_version, monkeypatch
):
    seen: dict = {}

    def _fake(*_args, **kwargs):
        seen.update(kwargs)
        return json.dumps(VALID_RESULT), "openai", "gpt-4o-mini", _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.orchestrator.call_with_rotation", _fake)
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block", lambda db: ""
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )

    rewrite_cluster(
        clean_db,
        RewriteSettings(),
        prompt_version,
        sources_text="x" * 3000,
        facts_text="facts",
        flags_text="flags",
    )

    assert "цель 2400–3600" in seen["system_prompt"]
    assert "около 3000 символов" in seen["system_prompt"]
    assert "НЕОТМЕНИМАЯ ПРОВЕРКА ВЕРНОСТИ" in seen["system_prompt"]
    assert "ПУНКТУАЦИЯ" in seen["system_prompt"]
    assert "Никогда не приписывай дате отсутствующий в оригинале год" in seen["system_prompt"]
    assert "биткоин» и «эфир" in seen["system_prompt"]
    assert "цель 2400-3600" in seen["user_prompt"]


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
    seen: dict = {}

    def _fake(*a, **kw):
        seen.update(kw)
        return (json.dumps(VALID_RESULT), "openai", "gpt-4o-mini", _USAGE)

    monkeypatch.setattr("rewrite_app.rewrite.orchestrator.call_with_rotation", _fake)
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block",
        lambda db: "",
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug",
        lambda slug, **kw: slug or "world",
    )

    result, key_alias, model, usage, _review_report = rewrite_cluster(
        clean_db,
        RewriteSettings(),
        prompt_version,
        sources_text="s",
        facts_text="f",
        flags_text="fl",
        prefer_key_alias="openai",
    )

    assert result.title_en == VALID_RESULT["title_en"]
    assert result.disclaimer_flag is True
    assert len(result.tags) == 1
    assert key_alias == "openai"
    assert model == "gpt-4o-mini"
    assert usage.total_tokens == 17
    assert seen.get("prefer_key_alias") == "openai"
    assert seen.get("advance") is False


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


def test_rewrite_cluster_accepts_body_over_soft_max(clean_db, prompt_version, monkeypatch):
    """Bodies longer than soft aspiration (~3000) must not be regenerated."""
    _enable_both_locales(clean_db)
    long_ok = dict(VALID_RESULT, body_en="x" * (BODY_SOFT_MAX_CHARS + 500))
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.call_with_rotation",
        lambda *a, **kw: (json.dumps(long_ok), "openai", "gpt-4o-mini", _USAGE),
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
        RewriteSettings(anthropic_api_key="editor-key"),
        prompt_version,
        sources_text="s",
        facts_text="f",
        flags_text="fl",
    )
    assert len(result.body_en) > BODY_SOFT_MAX_CHARS


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


def test_rewrite_cluster_edits_short_draft_with_previous_json(
    clean_db, prompt_version, monkeypatch
):
    _enable_both_locales(clean_db)
    short = dict(
        VALID_RESULT,
        body_ru="Короткий подтвержденный текст.\n\nВторой абзац.\n\nТретий абзац.",
    )
    calls: list[dict] = []

    def _fake(*_args, **kwargs):
        calls.append(kwargs)
        payload = short if len(calls) == 1 else VALID_RESULT
        return json.dumps(payload), "openai", "gpt-4o-mini", _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.orchestrator.call_with_rotation", _fake)
    monkeypatch.setattr(
        "rewrite_app.rewrite.orchestrator.site_category_prompt_block", lambda db: ""
    )
    monkeypatch.setattr(
        "common.site_categories.resolve_site_category_slug", lambda slug, **kw: slug or "world"
    )

    result, *_ = rewrite_cluster(
        clean_db,
        RewriteSettings(anthropic_api_key="editor-key"),
        prompt_version,
        sources_text="source facts",
        facts_text="facts",
        flags_text="flags",
    )

    assert result.body_ru == VALID_BODY_RU
    assert len(calls) == 2
    assert "РЕДАКТОРСКИЙ ПРОХОД ПО ДЛИНЕ" in calls[1]["user_prompt"]
    assert short["body_ru"] in calls[1]["user_prompt"]
    assert "ПРЕДЫДУЩИЙ_JSON" in calls[1]["user_prompt"]
    assert calls[1]["prefer_key_alias"] == "anthropic"
