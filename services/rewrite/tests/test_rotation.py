from __future__ import annotations

from db.models import LlmRotationModel, LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError
from rewrite_app.rewrite.rotation import (
    FREE_MODELS,
    AllKeysExhaustedError,
    active_free_models,
    call_with_rotation,
)


def test_first_key_success_records_usage(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: ("content", "openai/gpt-oss-20b:free"),
    )

    content, key_alias, model = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert content == "content"
    assert key_alias == "key_1"
    usage = clean_db.get(LLMRotationUsage, ("key_1", "openai/gpt-oss-20b:free"))
    assert usage.usage_count == 1
    assert usage.error_count == 0


def test_cascades_to_next_key_on_failure(clean_db, monkeypatch):
    calls = []

    def _fake(*, api_key, **kw):
        calls.append(api_key)
        if api_key == "a":
            raise OpenRouterError("exhausted")
        return "content", "openai/gpt-oss-20b:free"

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _fake)

    content, key_alias, model = call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert calls == ["a", "b"]
    assert key_alias == "key_2"
    failed_usage = clean_db.get(LLMRotationUsage, ("key_1", "<exhausted-before-response>"))
    assert failed_usage.error_count == 1

    # the switch is now persisted — a fresh call should start at key_2
    calls.clear()
    monkeypatch.setattr(
        "rewrite_app.rewrite.rotation.call_openrouter",
        lambda **kw: ("content2", "openai/gpt-oss-20b:free"),
    )
    _, key_alias_2, _ = call_with_rotation(
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

    with pytest.raises(AllKeysExhaustedError):
        call_with_rotation(
            clean_db,
            api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
            system_prompt="s",
            user_prompt="u",
        )


def test_missing_key_is_skipped(clean_db, monkeypatch):
    calls = []

    def _fake(*, api_key, **kw):
        calls.append(api_key)
        return "content", "openai/gpt-oss-20b:free"

    monkeypatch.setattr("rewrite_app.rewrite.rotation.call_openrouter", _fake)

    _, key_alias, _ = call_with_rotation(
        clean_db,
        api_keys={"key_1": "", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )
    assert key_alias == "key_2"
    assert calls == ["b"]


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
        lambda *, models, **kw: (seen_models.append(models), ("content", models[0]))[1],
    )

    call_with_rotation(
        clean_db,
        api_keys={"key_1": "a", "key_2": "b", "key_3": "c"},
        system_prompt="s",
        user_prompt="u",
    )

    assert seen_models == [[FREE_MODELS[1]]]
