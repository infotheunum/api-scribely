from __future__ import annotations

import os
import re

import pytest
from rewrite_app.enrich.enrichment import enrich_cluster
from rewrite_app.prompt.versions import get_active_prompt_version
from rewrite_app.rewrite.orchestrator import rewrite_cluster
from rewrite_app.settings import RewriteSettings

REAL_SOURCE_EN = """\
[Coinbase Misses Q2 Earnings as Crypto Trading Activity Slows] (The Block Wire, en, tier 1, https://example.com/en)
Coinbase reported second-quarter earnings below Wall Street expectations on Thursday, as
trading volumes across the crypto exchange slowed compared to the previous quarter.
The company posted a surprise net loss for the period, contrasting with a profit a year
earlier. Executives pointed to lower retail trading activity and cited stablecoin revenue
as a bright spot. Shares fell in after-hours trading following the report.
"""

REAL_SOURCE_RU = """\
[Coinbase не оправдала ожиданий по прибыли во втором квартале] (The Block Wire, ru, tier 1, https://example.com/ru)
Биржа Coinbase во втором квартале показала результаты хуже ожиданий аналитиков Уолл-стрит
на фоне замедления торговой активности. Компания неожиданно зафиксировала чистый убыток за
период, тогда как годом ранее была прибыль. Руководство связало это со снижением розничной
торговой активности, отметив рост выручки от стейблкоинов. Акции упали на постторговых торгах.
"""


@pytest.mark.skipif(
    not any(
        os.environ.get(k, "").strip()
        for k in ("OPENROUTER_KEY_1", "OPENROUTER_KEY_2", "OPENROUTER_KEY_3")
    ),
    reason="OPENROUTER_KEY_* not configured — live LLM test skipped",
)
def test_real_end_to_end_enrich_and_rewrite(clean_db):
    """Slow and hits real OpenRouter free-tier quota on purpose — this is
    the one test in the suite that proves the whole pipeline (prompt +
    rotation + JSON schema) actually works against a real model's real
    output, not just against my own mocks. Everything else in this file
    tree mocks the LLM call deliberately."""
    settings = RewriteSettings()
    sources_text = REAL_SOURCE_EN + "\n\n" + REAL_SOURCE_RU

    enrich_result, enrich_key, enrich_model, enrich_usage = enrich_cluster(
        clean_db, settings, sources_text=sources_text
    )
    assert len(enrich_result.facts) > 0
    print(
        f"\n[enrich] key={enrich_key} model={enrich_model} "
        f"tokens={enrich_usage.total_tokens} facts={enrich_result.facts}"
    )

    prompt_version = get_active_prompt_version(clean_db)
    facts_text = "\n".join(f"- [{f.kind}] {f.text}" for f in enrich_result.facts)
    flags_text = (
        f"press_release={enrich_result.press_release}, regulated={enrich_result.regulated}, "
        f"market_sensitive={enrich_result.market_sensitive}"
    )

    result, key_alias, model, rewrite_usage = rewrite_cluster(
        clean_db,
        settings,
        prompt_version,
        sources_text=sources_text,
        facts_text=facts_text,
        flags_text=flags_text,
    )

    print(f"\n[rewrite] key={key_alias} model={model} tokens={rewrite_usage.total_tokens}")
    print(f"EN title: {result.title_en}")
    print(f"EN body: {result.body_en}")
    print(f"RU title: {result.title_ru}")
    print(f"RU body: {result.body_ru}")
    print(f"SEO EN: {result.seo_en}")
    print(f"Tags: {result.tags}")

    # Real correctness checks, not just "did it parse":
    assert len(result.title_en) > 10
    assert "coinbase" in result.title_en.lower() or "coinbase" in result.body_en.lower()
    # RU fields should actually contain Cyrillic, not just be an EN copy.
    assert re.search(r"[а-яА-Я]", result.title_ru)
    assert re.search(r"[а-яА-Я]", result.body_ru)
    # Style guide rule: no "ё" in the Russian text.
    assert "ё" not in result.title_ru
    assert "ё" not in result.body_ru
    assert len(result.seo_en.keywords) > 0
    assert len(result.tags) > 0
    # Regression check for a real bug: with no outlet name in the source
    # data, the model attributed to "Cointelegraph" — an example outlet
    # name lifted verbatim from the system prompt's attribution
    # instruction, not anything present in the actual sources. Sources
    # here are deliberately attributed to a made-up outlet ("The Block
    # Wire") unlikely to be the model's own prior for crypto news, so
    # seeing it in the output proves attribution is grounded in the real
    # source_name field rather than invented.
    assert "the block wire" in result.body_en.lower()
