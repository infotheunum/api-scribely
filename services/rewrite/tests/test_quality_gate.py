from __future__ import annotations

import json

from common.token_usage import TokenUsage
from rewrite_app.rewrite.quality_gate import review_rewrite
from rewrite_app.settings import RewriteSettings


def _review_payload(
    *,
    approved: bool,
    semantic_findings: list[dict] | None = None,
    language_issues: list[str] | None = None,
    blocking_issues: list[str] | None = None,
):
    return json.dumps(
        {
            "approved": approved,
            "issues": [],
            "semantic_findings": semantic_findings or [],
            "language_issues": language_issues or [],
            "editorial_review_flags": [],
            "blocking_issues": blocking_issues or [],
        }
    )


def _fake_response(payload: str):
    return lambda *args, **kwargs: (payload, "openai", "editor-model", TokenUsage(1, 2, 3))


def test_quality_gate_rejects_critical_semantic_finding(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                semantic_findings=[
                    {
                        "severity": "critical",
                        "message": "перепутаны причина и следствие",
                        "source_span": "из-за роста",
                        "rewrite_span": "рост из-за",
                    }
                ],
            )
        ),
    )

    approved, issues, report, *_ = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="original",
        required_facts_text="(нет)",
        rewritten_text="rewrite",
        translate_sources=False,
    )

    assert approved is False
    assert any("причина" in issue for issue in issues)
    assert report["filters"]["semantic"]["status"] == "critical"


def test_quality_gate_rejects_language_errors_even_when_model_approves(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                language_issues=["«индивидуальная потолок» — ошибка согласования"],
            )
        ),
    )

    approved, issues, *_ = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="original",
        required_facts_text="(нет)",
        rewritten_text="rewrite",
        translate_sources=False,
    )

    assert approved is False
    assert issues == ["«индивидуальная потолок» — ошибка согласования"]


def test_quality_gate_ignores_no_errors_prose_in_language_issue_array(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=False,
                language_issues=["Нет ошибок перевода, грамматики или неуместных англицизмов."],
            )
        ),
    )

    approved, issues, report, *_ = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="original",
        required_facts_text="(нет)",
        rewritten_text="rewrite",
        translate_sources=False,
    )

    assert approved is True
    assert issues == []
    assert report["language_issues"] == []


def test_quality_gate_allows_warning_only_semantic_findings(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                semantic_findings=[
                    {
                        "severity": "warning",
                        "message": "повтор одной мысли",
                        "rewrite_span": "снова о росте",
                    }
                ],
            )
        ),
    )

    approved, issues, report, *_ = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="original",
        required_facts_text="(нет)",
        rewritten_text="rewrite",
        translate_sources=False,
    )

    assert approved is True
    assert issues == []
    assert report["filters"]["semantic"]["status"] == "warning"


def test_quality_gate_runs_source_translation_separately_after_approval(clean_db, monkeypatch):
    calls: list[dict] = []

    def _fake(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return (
                _review_payload(approved=True),
                "openai",
                "editor-model",
                TokenUsage(1, 2, 3),
            )
        return (
            json.dumps(
                {
                    "translations": [
                        {"title": "Original", "body_ru": "Полный перевод оригинала"}
                    ]
                }
            ),
            "anthropic",
            "translator-model",
            TokenUsage(4, 5, 9),
        )

    monkeypatch.setattr("rewrite_app.rewrite.quality_gate.call_with_rotation", _fake)

    approved, _issues, report, _key, _model, usage = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="Original source",
        required_facts_text="(нет)",
        rewritten_text="rewrite",
        translate_sources=True,
    )

    assert approved is True
    assert len(calls) == 2
    assert "смысловой редактор" in calls[0]["system_prompt"]
    assert "ПОЛНОГО ПЕРЕВОДА" in calls[1]["user_prompt"]
    assert report["translations"] == [
        {"title": "Original", "body_ru": "Полный перевод оригинала"}
    ]
    assert usage.total_tokens == 12
