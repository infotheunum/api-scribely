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
    assert result["missing"]["status"] == "critical"


def test_filter_ignores_tweet_or_article_ids_in_urls():
    source = (
        "Пост на X: https://x.com/user/status/1970123456789012345 сообщает, что фонд купил 100 BTC."
    )
    rewrite = "Фонд купил 100 BTC, сообщил источник в соцсети."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    missing_msgs = " ".join(f["message"] for f in result["missing"]["findings"])
    invented_msgs = " ".join(f["message"] for f in result["invented"]["findings"])
    assert "1970123456789012345" not in missing_msgs
    assert "1970123456789012345" not in invented_msgs
    assert result["missing"]["status"] != "critical"
    assert result["invented"]["status"] != "critical"


def test_filter_plain_integer_id_is_not_critical():
    source = "Статья 1052 описывает запуск продукта."
    rewrite = "Компания запустила продукт."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    # four-digit plain ints still extract, but must not block as critical money/crypto.
    critical = [f for f in result["missing"]["findings"] if f["severity"] == "critical"]
    assert not any("1052" in f["message"] for f in critical)


def test_filter_month_only_missing_is_warning():
    source = "Сделка обсуждалась в September на конференции."
    rewrite = "Сделка обсуждалась на конференции."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    month_missing = [f for f in result["missing"]["findings"] if "дата" in f["message"]]
    assert month_missing
    assert all(f["severity"] == "warning" for f in month_missing)


def test_filter_title_case_headline_noise_not_invented_name():
    source = "Company announced a token sale after restructuring."
    rewrite = "Why Did Token Sale Spins Out Months After Restructuring"
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    invented_names = [
        f
        for f in result["invented"]["findings"]
        if "имени" in f["message"] or "нет в источнике" in f["message"]
    ]
    noise = ("Why Did", "Token Sale", "Spins Out", "Months After")
    # Title-case headline fragments must not look like person/org inventions.
    assert not any(any(tok in f.get("rewrite_span", "") for tok in noise) for f in invented_names)


def test_filter_missing_only_checks_required_facts_not_full_cluster():
    """Multi-article clusters list many figures; rewrite must keep required ones."""
    source = (
        "Fund bought 100 BTC. Separately markets saw $17.2 billion flows, "
        "$71 billion AUM, 847,666 BTC held elsewhere, and a $13.7 billion deal."
    )
    required = "- [number] 100 BTC\n- [who] Fund\n- [essence] Fund bought bitcoin"
    rewrite = "Fund bought 100 BTC, according to the report."
    result = compare_facts(
        source_text=source,
        rewrite_text=rewrite,
        required_text=required,
    )
    missing_msgs = " ".join(f["message"] for f in result["missing"]["findings"])
    assert "17.2" not in missing_msgs
    assert "71" not in missing_msgs
    assert "847" not in missing_msgs
    assert result["missing"]["status"] != "critical"


def test_filter_missing_still_blocks_when_required_money_absent():
    source = "Fund bought 100 BTC at $79 670 average."
    required = "- [number] $79 670\n- [number] 100 BTC"
    rewrite = "Fund bought 100 BTC."
    result = compare_facts(
        source_text=source,
        rewrite_text=rewrite,
        required_text=required,
    )
    assert result["missing"]["status"] == "critical"
    assert any("79" in f["message"] for f in result["missing"]["findings"])


def test_filter_60k_equals_60000_not_distortion():
    source = "Bitcoin traded between $60k and $80k."
    rewrite = "Bitcoin traded between $60 000 and $80 000."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert result["distorted"]["findings"] == []
    assert result["missing"]["status"] != "critical"


def test_filter_chart_jargon_not_missing_name():
    source = "Traders watched an Accumulation Pattern near support."
    rewrite = "Traders watched buying near support."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert not any("Accumulation Pattern" in f["message"] for f in result["missing"]["findings"])


def test_filter_fuzzy_translit_name_not_missing():
    """Cathie Wood ↔ Кэти Вуд should count as covered without exact string match."""
    source = "Cathie Wood said tokenization opens a path for investors."
    rewrite = "Кэти Вуд заявила, что токенизация открывает путь для инвесторов."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert not any("Cathie Wood" in f["message"] for f in result["missing"]["findings"])
    assert not any("Кэти Вуд" in f.get("rewrite_span", "") for f in result["invented"]["findings"])


def test_filter_fluff_rewrite_low_entity_coverage():
    """Topic-only prose without source figures/names must fail coverage floor."""
    source = (
        "Uniswap processed $82.8 million in tokenized stocks, holding a 73% share "
        "on Robinhood Chain. Sam Altman spoke at DevDay about Spaces."
    )
    rewrite = (
        "Токенизация продолжает трансформировать традиционные финансовые системы, "
        "открывая новые возможности для участников рынка и меняя инфраструктуру."
    )
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    assert result["missing"]["status"] == "critical"
    assert result["missing"]["entity_coverage_pct"] < 35
    assert any(f.get("category") == "entity_coverage" for f in result["missing"]["findings"])


def test_filter_invented_translated_name_is_warning_not_blocker():
    source = "Rect Capital announced a sale."
    rewrite = "Ректа Капитала объявила о продаже."
    result = compare_facts(source_text=source, rewrite_text=rewrite)
    critical = [
        f
        for f in result["invented"]["findings"]
        if f["severity"] == "critical" and "Ректа" in f.get("rewrite_span", "")
    ]
    assert critical == []
    assert result["invented"]["status"] != "critical"


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
    rewrite = "Аналитик заявил: «Рынок обречён на крах в ближайшие дни»."
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert result["status"] == "critical"
    assert any("придумана" in f["message"] for f in result["findings"])


def test_filter_distorted_quote_partial_rewrite():
    source = "Директор сказал: «Мы увеличим инвестиции в инфраструктуру на 40 процентов»."
    rewrite = "Директор сказал: «Мы увеличим расходы на маркетинг в следующем квартале»."
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert result["status"] == "critical"
    assert any(
        "искажена" in f["message"] or "придумана" in f["message"] for f in result["findings"]
    )


def test_filter_quote_missing_author():
    source = "«Мы готовы к запуску», — сказал Иванов."
    rewrite = "«Мы готовы к запуску»."
    result = check_quotes(source_text=source, rewrite_text=rewrite)
    assert any("нет автора" in f["message"] for f in result["findings"])


def test_banned_phrase_outside_quotes():
    rewrite = "Таким образом рынок вырос."
    result = find_banned_phrases(rewrite)
    assert result["findings"]
    assert any("таким образом" in f["rewrite_span"].casefold() for f in result["findings"])


def test_banned_phrase_ignored_inside_quotes():
    rewrite = "Спикер сказал: «Таким образом мы победим»."
    result = find_banned_phrases(rewrite)
    assert result["findings"] == []


def test_get_banned_phrases_merges_code_defaults_over_stale_db(clean_db):
    """Old AppSetting (5 invest phrases) must still pick up new code defaults."""
    from rewrite_app.rewrite.banned_phrases import (
        DEFAULT_BANNED_PHRASES,
        get_banned_phrases,
        set_banned_phrases,
    )

    set_banned_phrases(
        clean_db,
        [
            {"phrase": "следите", "category": "investment"},
            {"phrase": "стоит купить", "category": "investment"},
        ],
    )
    merged = get_banned_phrases(clean_db)
    phrases = {p["phrase"].casefold() for p in merged}
    assert "следите" in phrases
    assert "точка входа" in phrases
    assert "добиться прорыва" in phrases
    assert len(merged) >= len(DEFAULT_BANNED_PHRASES)


def test_investment_phrase_entry_point_flagged():
    rewrite = "Это потенциальная точка входа для покупки токена."
    result = find_banned_phrases(rewrite)
    assert any(f.get("category") == "investment" for f in result["findings"])


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
    # Do not spend semantic LLM tokens when filters 1–5 already block.
    assert report["filters"]["semantic"].get("status") == "skipped"
