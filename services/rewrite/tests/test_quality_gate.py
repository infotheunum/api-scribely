from __future__ import annotations

import json

from common.token_usage import TokenUsage
from rewrite_app.rewrite.quality_gate import review_rewrite
from rewrite_app.settings import RewriteSettings


def _review_payload(
    *,
    approved: bool,
    fact_checks: list[dict],
    language_issues: list[str] | None = None,
    required_fact_checks: list[dict] | None = None,
):
    return json.dumps(
        {
            "approved": approved,
            "issues": [],
            "language_issues": language_issues or [],
            "fact_checks": fact_checks,
            "required_fact_checks": required_fact_checks or [],
            "translations": [],
        }
    )


def _fake_response(payload: str):
    return lambda *args, **kwargs: (payload, "openai", "editor-model", TokenUsage(1, 2, 3))


def test_quality_gate_rejects_inconsistent_approved_verdict_for_distortion(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                fact_checks=[
                    {
                        "fact": "лимит займа составляет $10 млн",
                        "status": "искажён",
                        "severity": "secondary",
                        "rewrite_evidence": "лимит не указан",
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
    assert any("искажён" in issue for issue in issues)
    assert report["fact_checks"][0]["status"] == "искажён"


def test_quality_gate_rejects_language_errors_even_when_model_approves(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                fact_checks=[
                    {
                        "fact": "компания запустила рынок",
                        "status": "совпадает",
                        "severity": "critical",
                        "rewrite_evidence": "рынок запущен",
                    }
                ],
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
                fact_checks=[
                    {
                        "fact": "компания запустила рынок",
                        "status": "совпадает",
                        "severity": "critical",
                        "rewrite_evidence": "рынок запущен",
                    }
                ],
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


def test_quality_gate_allows_omission_even_when_model_marks_it_critical(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                fact_checks=[
                    {
                        "fact": "второстепенная деталь",
                        "status": "упущен",
                        "severity": "critical",
                        "rewrite_evidence": "",
                    }
                ],
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

    assert approved is True
    assert issues == []


def test_quality_gate_rejects_missing_required_fact(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        _fake_response(
            _review_payload(
                approved=True,
                fact_checks=[],
                required_fact_checks=[
                    {
                        "required_fact": "- [number] IPO привлекло заявки в 6 000 раз выше объема акций",
                        "status": "упущен",
                        "rewrite_evidence": "",
                    }
                ],
            )
        ),
    )

    approved, issues, *_ = review_rewrite(
        clean_db,
        RewriteSettings(),
        sources_text="original",
        required_facts_text="- [number] IPO привлекло заявки в 6 000 раз выше объема акций",
        rewritten_text="rewrite",
        translate_sources=False,
    )

    assert approved is False
    assert any("обязательный факт упущен" in issue for issue in issues)
