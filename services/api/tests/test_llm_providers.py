from __future__ import annotations

from common.llm_providers import (
    DEFAULT_ENABLED_PROVIDERS,
    get_enabled_providers,
    parse_enabled_providers,
    set_enabled_providers,
)


def test_parse_enabled_providers_default_openai():
    assert parse_enabled_providers(None) == list(DEFAULT_ENABLED_PROVIDERS)
    assert parse_enabled_providers("") == ["openai"]
    assert parse_enabled_providers([]) == ["openai"]


def test_parse_enabled_providers_json_and_csv():
    assert parse_enabled_providers('["qwen","openai"]') == ["qwen", "openai"]
    assert parse_enabled_providers("anthropic, openai") == ["openai", "anthropic"]


def test_set_enabled_providers_roundtrip(clean_db):
    assert set_enabled_providers(clean_db, ["openai", "qwen"]) == ["qwen", "openai"]
    clean_db.commit()
    assert get_enabled_providers(clean_db) == ["qwen", "openai"]
