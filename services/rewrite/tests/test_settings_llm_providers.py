from __future__ import annotations

from rewrite_app.settings import RewriteSettings


def test_llm_enabled_providers_empty_defaults_to_openai(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "q")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("LLM_ENABLED_PROVIDERS", raising=False)
    settings = RewriteSettings()
    keys = settings.llm_provider_keys()
    assert keys["qwen"] == ""
    assert keys["openai"] == "o"
    assert keys["anthropic"] == ""


def test_llm_enabled_providers_qwen_only_blanks_others(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "q")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("LLM_ENABLED_PROVIDERS", "qwen")
    settings = RewriteSettings()
    keys = settings.llm_provider_keys()
    assert keys["qwen"] == "q"
    assert keys["openai"] == ""
    assert keys["anthropic"] == ""


def test_llm_enabled_providers_case_and_spaces(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "q")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("LLM_ENABLED_PROVIDERS", " Qwen , Anthropic ")
    settings = RewriteSettings()
    keys = settings.llm_provider_keys()
    assert keys["qwen"] == "q"
    assert keys["openai"] == ""
    assert keys["anthropic"] == "a"


def test_llm_enabled_providers_appsetting_overrides_env(clean_db, monkeypatch):
    from common.llm_providers import set_enabled_providers

    monkeypatch.setenv("QWEN_API_KEY", "q")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("LLM_ENABLED_PROVIDERS", "qwen,anthropic")
    set_enabled_providers(clean_db, ["openai"])
    clean_db.commit()

    settings = RewriteSettings()
    keys = settings.llm_provider_keys(clean_db)
    assert keys["openai"] == "o"
    assert keys["qwen"] == ""
    assert keys["anthropic"] == ""
