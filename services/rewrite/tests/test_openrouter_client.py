from __future__ import annotations

import httpx
import pytest
from rewrite_app.rewrite.openrouter_client import OpenRouterError, call_openrouter, extract_json


def test_extract_json_strips_markdown_fence():
    content = '```json\n{"a": 1}\n```'
    assert extract_json(content) == {"a": 1}


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        return self._payload


def test_call_openrouter_returns_content_and_model(monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.openrouter_client.httpx.post",
        lambda *a, **kw: _FakeResponse(
            {"choices": [{"message": {"content": "{}"}}], "model": "openai/gpt-oss-20b:free"}
        ),
    )
    content, model = call_openrouter(api_key="k", models=["m"], system_prompt="s", user_prompt="u")
    assert content == "{}"
    assert model == "openai/gpt-oss-20b:free"


def test_call_openrouter_raises_on_error_field(monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.openrouter_client.httpx.post",
        lambda *a, **kw: _FakeResponse({"error": {"message": "rate limited"}}),
    )
    with pytest.raises(OpenRouterError):
        call_openrouter(api_key="k", models=["m"], system_prompt="s", user_prompt="u")


def test_call_openrouter_raises_on_transport_error(monkeypatch):
    def _raise(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("rewrite_app.rewrite.openrouter_client.httpx.post", _raise)
    with pytest.raises(OpenRouterError):
        call_openrouter(api_key="k", models=["m"], system_prompt="s", user_prompt="u")
