from __future__ import annotations

from db.models import LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation


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
