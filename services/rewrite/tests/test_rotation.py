from __future__ import annotations

import pytest
from common.token_usage import TokenUsage
from db.app_settings import get_setting
from db.models import LlmRotationModel, LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError
from rewrite_app.rewrite.rotation import (
    FREE_MODELS,
    ROUND_ROBIN_INDEX_KEY,
    AllKeysExhaustedError,
    active_free_models,
    call_with_rotation,
    pick_next_primary,
)

_USAGE = TokenUsage(prompt_tokens=11, completion_tokens=22, total_tokens=33)

_ALL_KEYS = {
    "qwen": "q-key",
    "openai": "o-key",
    "anthropic": "a-key",
    "key_1": "or1",
    "key_2": "or2",
    "key_3": "or3",
}


def _patch_primaries(monkeypatch, *, qwen=None, openai=None, anthropic=None, openrouter=None):
    """Install provider fakes. Default: each succeeds with its model id."""

    def _ok(*, model, **kw):
        return "content", model, _USAGE

    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_qwen",
        qwen if qwen is not None else _ok,
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openai",
        openai if openai is not None else _ok,
    )
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_anthropic",
        anthropic if anthropic is not None else _ok,
    )

    def _or_default(**kw):
        raise AssertionError("OpenRouter must not be called in article RR")

    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        openrouter if openrouter is not None else _or_default,
    )


def test_advance_round_robins_across_primaries(clean_db, monkeypatch):
    order: list[str] = []

    def _qwen(*, model, **kw):
        order.append("qwen")
        return "c", model, _USAGE

    def _openai(*, model, **kw):
        order.append("openai")
        return "c", model, _USAGE

    def _anthropic(*, model, **kw):
        order.append("anthropic")
        return "c", model, _USAGE

    _patch_primaries(monkeypatch, qwen=_qwen, openai=_openai, anthropic=_anthropic)

    aliases = []
    for _ in range(4):
        _, key_alias, _, _ = call_with_rotation(
            clean_db,
            api_keys=_ALL_KEYS,
            system_prompt="s",
            user_prompt="u",
            advance=True,
        )
        aliases.append(key_alias)

    assert aliases == ["qwen", "openai", "anthropic", "qwen"]
    assert order == aliases
    assert int(get_setting(clean_db, ROUND_ROBIN_INDEX_KEY, 0)) == 4


def test_prefer_key_alias_pins_without_advancing(clean_db, monkeypatch):
    _patch_primaries(monkeypatch)
    pick_next_primary(clean_db, _ALL_KEYS)  # cursor → 1 (next would be openai)

    calls: list[str] = []

    def _openai(*, model, **kw):
        calls.append("openai")
        return "c", model, _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openai", _openai)

    for _ in range(2):
        _, key_alias, model, usage = call_with_rotation(
            clean_db,
            api_keys=_ALL_KEYS,
            system_prompt="s",
            user_prompt="u",
            prefer_key_alias="openai",
            advance=False,
        )
        assert key_alias == "openai"
        assert usage.total_tokens == 33

    assert calls == ["openai", "openai"]
    # prefer must not advance the global cursor further
    assert int(get_setting(clean_db, ROUND_ROBIN_INDEX_KEY, 0)) == 1


def test_failover_walks_remaining_primaries(clean_db, monkeypatch):
    order: list[str] = []

    def _qwen(**kw):
        order.append("qwen")
        raise OpenRouterError("qwen down")

    def _openai(**kw):
        order.append("openai")
        raise OpenRouterError("openai down")

    def _anthropic(*, model, **kw):
        order.append("anthropic")
        return "content", model, _USAGE

    _patch_primaries(monkeypatch, qwen=_qwen, openai=_openai, anthropic=_anthropic)

    _, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys=_ALL_KEYS,
        system_prompt="s",
        user_prompt="u",
        advance=True,
    )

    assert order == ["qwen", "openai", "anthropic"]
    assert key_alias == "anthropic"
    assert usage.total_tokens == 33
    failed = clean_db.get(LLMRotationUsage, ("qwen", "<exhausted-before-response>"))
    assert failed is not None and failed.error_count == 1


def test_prefer_failover_starts_at_preferred(clean_db, monkeypatch):
    order: list[str] = []

    def _openai(**kw):
        order.append("openai")
        raise OpenRouterError("openai down")

    def _anthropic(*, model, **kw):
        order.append("anthropic")
        return "ok", model, _USAGE

    def _qwen(**kw):
        order.append("qwen")
        raise AssertionError("qwen must not run before openai prefer failover cycle")

    _patch_primaries(monkeypatch, qwen=_qwen, openai=_openai, anthropic=_anthropic)

    _, key_alias, _, _ = call_with_rotation(
        clean_db,
        api_keys=_ALL_KEYS,
        system_prompt="s",
        user_prompt="u",
        prefer_key_alias="openai",
    )

    assert order == ["openai", "anthropic"]
    assert key_alias == "anthropic"


def test_all_primaries_exhausted_raises(clean_db, monkeypatch):
    def _fail(**kw):
        raise OpenRouterError("timeout connecting to provider")

    _patch_primaries(monkeypatch, qwen=_fail, openai=_fail, anthropic=_fail)

    with pytest.raises(AllKeysExhaustedError) as exc_info:
        call_with_rotation(
            clean_db,
            api_keys=_ALL_KEYS,
            system_prompt="s",
            user_prompt="u",
            advance=True,
        )
    assert exc_info.value.code == "openrouter_keys_exhausted"


def test_all_primaries_exhausted_preserves_payment_code(clean_db, monkeypatch):
    def _fail(**kw):
        raise OpenRouterError(
            "HTTP 402: insufficient credits", code="openrouter_payment_required"
        )

    _patch_primaries(monkeypatch, qwen=_fail, openai=_fail, anthropic=_fail)

    with pytest.raises(AllKeysExhaustedError) as exc_info:
        call_with_rotation(
            clean_db,
            api_keys=_ALL_KEYS,
            system_prompt="s",
            user_prompt="u",
            advance=True,
        )
    assert exc_info.value.code == "openrouter_payment_required"


def test_no_primary_keys_raises(clean_db, monkeypatch):
    _patch_primaries(monkeypatch)
    with pytest.raises(AllKeysExhaustedError) as exc_info:
        call_with_rotation(
            clean_db,
            api_keys={"key_1": "or-only"},
            system_prompt="s",
            user_prompt="u",
            advance=True,
        )
    assert exc_info.value.code == "openrouter_no_keys_configured"


def test_skips_missing_primary_and_advances(clean_db, monkeypatch):
    """Configured primaries omit empty keys; RR only among present slots."""
    calls: list[str] = []

    def _openai(*, model, **kw):
        calls.append("openai")
        return "c", model, _USAGE

    def _anthropic(*, model, **kw):
        calls.append("anthropic")
        return "c", model, _USAGE

    _patch_primaries(monkeypatch, openai=_openai, anthropic=_anthropic)

    keys = {"qwen": "", "openai": "o", "anthropic": "a", "key_1": "x"}
    aliases = []
    for _ in range(3):
        _, alias, _, _ = call_with_rotation(
            clean_db,
            api_keys=keys,
            system_prompt="s",
            user_prompt="u",
            advance=True,
        )
        aliases.append(alias)

    assert aliases == ["openai", "anthropic", "openai"]
    assert calls == aliases


def test_records_usage_on_success(clean_db, monkeypatch):
    _patch_primaries(monkeypatch)
    content, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys=_ALL_KEYS,
        system_prompt="s",
        user_prompt="u",
        advance=True,
        qwen_model="qwen-plus",
    )
    assert content == "content"
    assert key_alias == "qwen"
    assert model == "qwen-plus"
    assert usage.total_tokens == 33
    row = clean_db.get(LLMRotationUsage, ("qwen", "qwen-plus"))
    assert row.usage_count == 1
    assert row.error_count == 0


def test_active_free_models_bootstraps_from_constant_on_first_use(clean_db):
    models = active_free_models(clean_db)

    assert models == FREE_MODELS
    assert clean_db.query(LlmRotationModel).count() == len(FREE_MODELS)


def test_active_free_models_reads_admin_edited_list(clean_db):
    active_free_models(clean_db)  # bootstrap
    clean_db.commit()
    row = clean_db.query(LlmRotationModel).filter_by(model_id=FREE_MODELS[0]).one()
    row.is_active = False
    clean_db.commit()

    models = active_free_models(clean_db)

    assert FREE_MODELS[0] not in models
    assert len(models) == len(FREE_MODELS) - 1
