from __future__ import annotations

from types import SimpleNamespace

from common.token_usage import TokenUsage
from rewrite_app.dedup import confirm_same_event
from scribely.rewrite.v1 import rewrite_pb2


def _source(title: str, text: str) -> rewrite_pb2.SourceRef:
    return rewrite_pb2.SourceRef(title=title, excerpt_or_full_text=text)


def test_confirm_same_event_uses_conservative_json_decision(monkeypatch):
    seen: dict = {}

    def fake_call(*args, **kwargs):
        seen.update(kwargs)
        return ('{"same_event": true}', "key_1", "model", TokenUsage(1, 2, 3))

    monkeypatch.setattr("rewrite_app.dedup.call_with_rotation", fake_call)
    same_event, key_alias, model, usage = confirm_same_event(
        None,
        SimpleNamespace(
            llm_provider_keys=lambda: [],
            anthropic_model="anthropic",
            openai_model="openai",
            qwen_model="qwen",
            qwen_base_url="https://example.com",
        ),
        incoming_sources=[_source("New report", "The company announced a launch.")],
        candidate_sources=[_source("Earlier report", "The same launch was announced.")],
    )

    assert same_event is True
    assert (key_alias, model, usage.total_tokens) == ("key_1", "model", 3)
    assert "НОВЫЙ МАТЕРИАЛ" in seen["user_prompt"]
    assert "КАНДИДАТ" in seen["user_prompt"]
