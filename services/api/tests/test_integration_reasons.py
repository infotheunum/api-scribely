from __future__ import annotations

from common.integration_reasons import (
    REASON_OPENROUTER_KEYS_EXHAUSTED,
    REASON_OPENROUTER_PAYMENT_REQUIRED,
    REASON_OPENROUTER_RATE_LIMITED,
    classify_openrouter_message,
    format_integration_error,
    parse_integration_error_detail,
    resolve_integration_error_code,
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


def test_classify_http_402():
    assert classify_openrouter_message("HTTP 402: Payment Required") == REASON_OPENROUTER_PAYMENT_REQUIRED


def test_format_and_resolve_structured_reason():
    raw = format_integration_error(
        REASON_OPENROUTER_RATE_LIMITED,
        "all OpenRouter keys exhausted: HTTP 429",
    )
    code, body = parse_integration_error_detail(raw)
    assert code == REASON_OPENROUTER_RATE_LIMITED
    assert "429" in body
    assert resolve_integration_error_code(raw) == REASON_OPENROUTER_RATE_LIMITED
