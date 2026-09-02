from __future__ import annotations

from common.token_usage import TokenUsage
from db.models import LlmRotationModel, LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError
from rewrite_app.rewrite.rotation import (
    FREE_MODELS,
    AllKeysExhaustedError,
    active_free_models,
    call_with_rotation,
)

_USAGE = TokenUsage(prompt_tokens=11, completion_tokens=22, total_tokens=33)


def test_first_key_success_records_usage(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: ("content", "openai/gpt-oss-20b:free", _USAGE),
    )

    content, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert content == "content"
    assert key_alias == "key_1"
    assert usage.total_tokens == 33
    row = clean_db.get(LLMRotationUsage, ("key_1", "openai/gpt-oss-20b:free"))
    assert row.usage_count == 1
    assert row.error_count == 0


def test_cascades_to_next_key_on_failure(clean_db, monkeypatch):
    calls = []

    def _fake(*, api_key, **kw):
        calls.append(api_key)
        if api_key == "a":
            raise OpenRouterError("exhausted")
        return "content", "openai/gpt-oss-20b:free", _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _fake)

    content, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert calls == ["a", "b"]
    assert key_alias == "key_2"
    assert usage.total_tokens == 33
    failed_usage = clean_db.get(LLMRotationUsage, ("key_1", "<exhausted-before-response>"))
    assert failed_usage.error_count == 1

    calls.clear()
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: ("content2", "openai/gpt-oss-20b:free", _USAGE),
    )
    _, key_alias_2, _, _ = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )
    assert key_alias_2 == "key_2"


def test_all_keys_exhausted_raises(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: (_ for _ in ()).throw(OpenRouterError("down")),
    )

    import pytest

    with pytest.raises(AllKeysExhaustedError) as exc_info:
        call_with_rotation(
            clean_db,
            api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
            system_prompt="s",
            user_prompt="u",
        )
    assert exc_info.value.code == "openrouter_keys_exhausted"


def test_all_keys_exhausted_preserves_payment_code(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: (_ for _ in ()).throw(
            OpenRouterError("HTTP 402: insufficient credits", code="openrouter_payment_required")
        ),
    )

    import pytest

    with pytest.raises(AllKeysExhaustedError) as exc_info:
        call_with_rotation(
            clean_db,
            api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
            system_prompt="s",
            user_prompt="u",
        )
    assert exc_info.value.code == "openrouter_payment_required"


def test_missing_key_is_skipped(clean_db, monkeypatch):
    calls = []

    def _fake(*, api_key, **kw):
        calls.append(api_key)
        return "content", "openai/gpt-oss-20b:free", _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _fake)

    _, key_alias, _, _ = call_with_rotation(
        clean_db,
        api_keys={"key_1": "", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )
    assert key_alias == "key_2"
    assert calls == ["b"]


def test_cascades_to_anthropic_after_openrouter(clean_db, monkeypatch):
    calls = []

    def _or(*, api_key, **kw):
        calls.append(("or", api_key))
        raise OpenRouterError("or down")

    def _anthropic(*, api_key, model, **kw):
        calls.append(("anthropic", api_key, model))
        return '{"ok":true}', model, _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _or)
    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_anthropic", _anthropic)

    content, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "", "key_3": "", "anthropic": "ant-key", "openai": ""},
        system_prompt="s",
        user_prompt="u",
        anthropic_model="claude-3-5-haiku-latest",
    )

    assert key_alias == "anthropic"
    assert model == "claude-3-5-haiku-latest"
    assert usage.total_tokens == 33
    assert calls[0][0] == "or"
    assert calls[-1][0] == "anthropic"


def test_cascades_openrouter_then_anthropic_then_openai(clean_db, monkeypatch):
    def _or(**kw):
        raise OpenRouterError("or down")

    def _anthropic(**kw):
        raise OpenRouterError("anthropic down")

    def _openai(*, model, **kw):
        return "content", model, _USAGE

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _or)
    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_anthropic", _anthropic)
    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openai", _openai)

    _, key_alias, model, usage = call_with_rotation(
        clean_db,
        api_keys={
            "key_1": "a",
            "key_2": "b",
            "key_3": "c",
            "anthropic": "ant",
            "openai": "oai",
        },
        system_prompt="s",
        user_prompt="u",
        openai_model="gpt-4o-mini",
    )

    assert key_alias == "openai"
    assert model == "gpt-4o-mini"
    assert usage.total_tokens == 33


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


def test_call_with_rotation_uses_admin_edited_model_list(clean_db, monkeypatch):
    active_free_models(clean_db)  # bootstrap
    clean_db.commit()
    for row in clean_db.query(LlmRotationModel).all():
        row.is_active = row.model_id == FREE_MODELS[1]
    clean_db.commit()

    seen_models = []
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda *, models, **kw: (seen_models.append(models), ("content", models[0], _USAGE))[1],
    )

    call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert seen_models == [[FREE_MODELS[1]]]
