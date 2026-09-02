from __future__ import annotations

import pytest
from rewrite_app.enrich.enrichment import enrich_cluster
from rewrite_app.rewrite.rotation import AllKeysExhaustedError
from rewrite_app.settings import RewriteSettings
from common.token_usage import TokenUsage

_USAGE = TokenUsage(1, 2, 3)


def test_enrich_cluster_parses_valid_response(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.enrich.enrichment.call_with_rotation",
        lambda *a, **kw: (
            '{"facts": [{"kind": "who", "text": "SEC"}], "press_release": false, '
            '"regulated": true, "market_sensitive": false, "fact_conflict": false, '
            '"fact_conflict_note": ""}',
            "key_1",
            "openai/gpt-oss-20b:free",
            _USAGE,
        ),
    )

    result, key_alias, model, usage = enrich_cluster(
        clean_db, RewriteSettings(), sources_text="some article text"
    )

    assert result.regulated is True
    assert len(result.facts) == 1
    assert key_alias == "key_1"
    assert usage.total_tokens == 3


def test_enrich_cluster_regenerates_on_invalid_json_then_succeeds(clean_db, monkeypatch):
    responses = iter(
        [
            ("not json at all", "key_1", "m", _USAGE),
            (
                '{"facts": [], "press_release": false, "regulated": false, '
                '"market_sensitive": false, "fact_conflict": false, "fact_conflict_note": ""}',
                "key_1",
                "m",
                _USAGE,
            ),
        ]
    )
    monkeypatch.setattr(
        "rewrite_app.enrich.enrichment.call_with_rotation", lambda *a, **kw: next(responses)
    )

    result, _, _, _ = enrich_cluster(clean_db, RewriteSettings(), sources_text="text")
    assert result.press_release is False


def test_enrich_cluster_raises_after_max_attempts_of_garbage(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.enrich.enrichment.call_with_rotation",
        lambda *a, **kw: ("not json", "key_1", "m", _USAGE),
    )
    with pytest.raises(RuntimeError, match="failed after"):
        enrich_cluster(clean_db, RewriteSettings(), sources_text="text")


def test_enrich_cluster_propagates_all_keys_exhausted(clean_db, monkeypatch):
    def _raise(*a, **kw):
        raise AllKeysExhaustedError("nope")

    monkeypatch.setattr("rewrite_app.enrich.enrichment.call_with_rotation", _raise)
    with pytest.raises(AllKeysExhaustedError):
        enrich_cluster(clean_db, RewriteSettings(), sources_text="text")
