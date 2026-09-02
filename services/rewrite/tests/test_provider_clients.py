from __future__ import annotations

import httpx
from rewrite_app.rewrite.openrouter_client import OpenRouterError
from rewrite_app.rewrite.provider_clients import call_anthropic, call_openai


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("POST", "https://x"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


def test_call_anthropic_returns_text(monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.provider_clients.httpx.post",
        lambda *a, **k: _Resp(
            {"model": "claude-3-5-haiku-latest", "content": [{"type": "text", "text": '{"a":1}'}]}
        ),
    )
    content, model = call_anthropic(
        api_key="k", model="claude-3-5-haiku-latest", system_prompt="s", user_prompt="u"
    )
    assert content == '{"a":1}'
    assert model == "claude-3-5-haiku-latest"


def test_call_openai_returns_content(monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.provider_clients.httpx.post",
        lambda *a, **k: _Resp(
            {"model": "gpt-4o-mini", "choices": [{"message": {"content": '{"b":2}'}}]}
        ),
    )
    content, model = call_openai(
        api_key="k", model="gpt-4o-mini", system_prompt="s", user_prompt="u"
    )
    assert content == '{"b":2}'
    assert model == "gpt-4o-mini"


def test_call_anthropic_raises_on_http_error(monkeypatch):
    def _post(*a, **k):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request, text="rate limit")
        raise httpx.HTTPStatusError("rate", request=request, response=response)

    monkeypatch.setattr("rewrite_app.rewrite.provider_clients.httpx.post", _post)
    import pytest

    with pytest.raises(OpenRouterError) as exc:
        call_anthropic(api_key="k", model="m", system_prompt="s", user_prompt="u")
    assert exc.value.code == "openrouter_rate_limited"
