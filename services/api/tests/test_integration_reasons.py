from __future__ import annotations

from common.integration_reasons import (
    REASON_OPENROUTER_KEYS_EXHAUSTED,
    REASON_OPENROUTER_PAYMENT_REQUIRED,
    REASON_OPENROUTER_RATE_LIMITED,
    classify_openrouter_message,
)


def test_classify_payment_required():
    assert (
        classify_openrouter_message("OpenRouter error: insufficient credits")
        == REASON_OPENROUTER_PAYMENT_REQUIRED
    )


def test_classify_rate_limited():
    assert classify_openrouter_message("HTTP 429: rate limit exceeded") == REASON_OPENROUTER_RATE_LIMITED


def test_classify_keys_exhausted():
    assert (
        classify_openrouter_message("all OpenRouter keys exhausted: down")
        == REASON_OPENROUTER_KEYS_EXHAUSTED
    )
