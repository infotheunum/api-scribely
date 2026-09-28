"""Unit tests for deterministic rewrite filters 1–5 (brief examples)."""

from __future__ import annotations

from common.token_usage import TokenUsage
from rewrite_app.rewrite.banned_phrases import find_banned_phrases
from rewrite_app.rewrite.fact_diff import compare_facts
from rewrite_app.rewrite.quote_check import check_quotes
from rewrite_app.rewrite.rewrite_review import run_filters_1_5, run_rewrite_review
from rewrite_app.settings import RewriteSettings


def test_filter_missing_average_price():
    source = "Фонд купил 950 BTC по средней цене $79 670."
    rewrite = "Фонд купил 950 BTC."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    messages = [f["message"] for f in result["missing"]["findings"]]
    assert any("79" in m or "79670" in m.replace(" ", "") for m in messages)
    assert result["missing"]["status"] in {"critical", "warning"}


def test_filter_invented_share_sale_amount():
    source = "Компания объявила о новой стратегии."
    rewrite = "Компания провела продажу акций на $80,1 млн."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    invented = result["invented"]["findings"]
    assert invented
    assert all(f["severity"] == "critical" for f in invented)
    assert any("80" in f["rewrite_span"] for f in invented)


def test_filter_distorted_magnitude():
    source = "Цена биткоина достигла $85 000."
    rewrite = "Цена биткоина достигла $85 000 000."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert result["distorted"]["findings"]
    assert result["distorted"]["status"] == "critical"


def test_filter_distorted_year_added_to_month():
    source = "Сделка закрылась в мае."
    rewrite = "Сделка закрылась в мае 2023."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert result["distorted"]["findings"]
    assert any("дата" in f["message"] for f in result["distorted"]["findings"])


def test_filter_invented_quote():
    source = "Аналитик отметил рост объёмов торгов."
    rewrite = 'Аналитик заявил: «Рынок обречён на крах в ближайшие дни».'
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert result["status"] == "critical"
    assert any("придумана" in f["message"] for f in result["findings"])


def test_filter_distorted_quote_partial_rewrite():
    source = 'Директор сказал: «Мы увеличим инвестиции в инфраструктуру на 40 процентов».'
    rewrite = 'Директор сказал: «Мы увеличим расходы на маркетинг в следующем квартале».'
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert result["status"] == "critical"
    assert any(
        "искажена" in f["message"] or "придумана" in f["message"]
        for f in result["findings"]
    )


def test_filter_quote_missing_author():
    source = '«Мы готовы к запуску», — сказал Иванов.'
    rewrite = '«Мы готовы к запуску».'
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert any("нет автора" in f["message"] for f in result["findings"])


def test_banned_phrase_outside_quotes():
    rewrite = "Таким образом рынок вырос."
    result = find_banned_phrases(rewrite)
    assert result["findings"]
    assert any("таким образом" in f["rewrite_span"].casefold() for f in result["findings"])


def test_banned_phrase_ignored_inside_quotes():
    rewrite = 'Спикер сказал: «Таким образом мы победим».'
    result = find_banned_phrases(rewrite)
    assert result["findings"] == []


def test_run_filters_1_5_summary_blocked_on_invention():
    filters = run_filters_1_5(
        source_text="Компания объявила о планах.",
        rewrite_text="Компания продала акции на $80,1 млн.",
    )
    assert filters["invented"]["status"] == "critical"


def test_run_rewrite_review_merges_deterministic_and_semantic(clean_db, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.rewrite.quality_gate.call_with_rotation",
        lambda *args, **kwargs: (
            '{"approved": true, "issues": [], "semantic_findings": [], '
            '"language_issues": [], "editorial_review_flags": [], "blocking_issues": []}',
            "openai",
            "editor",
            TokenUsage(1, 1, 2),
        ),
    )

    approved, issues, report, *_ = run_rewrite_review(
        clean_db,
        RewriteSettings(),
        sources_text="Фонд купил 950 BTC по $79 670.",
        facts_text="",
        required_facts_text="",
        rewritten_text="Фонд купил 950 BTC.",
        rewrite_plain_text="Фонд купил 950 BTC.",
        translate_sources=False,
    )

    assert "filters" in report
    assert "summary" in report
    assert report["summary"]["verdict"] in {"blocked", "needs_attention", "publishable"}
    # Missing average price should surface in fact_checks for legacy UI.
    assert any(c["status"] == "упущен" for c in report["fact_checks"])
    # Missing money figure is critical → gate fails.
    assert approved is False
    assert issues
