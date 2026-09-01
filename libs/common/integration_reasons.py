from __future__ import annotations

# Machine-readable codes returned to api.theunum.io cron (integrations API).

REASON_OK = "ok"
REASON_QUEUE_EMPTY = "queue_empty"
REASON_PIPELINE_DEGRADED = "pipeline_degraded"
REASON_OPENROUTER_KEYS_EXHAUSTED = "openrouter_keys_exhausted"
REASON_OPENROUTER_RATE_LIMITED = "openrouter_rate_limited"
REASON_OPENROUTER_PAYMENT_REQUIRED = "openrouter_payment_required"
REASON_OPENROUTER_AUTH_FAILED = "openrouter_auth_failed"
REASON_OPENROUTER_NO_KEYS = "openrouter_no_keys_configured"
REASON_DISPATCH_DISABLED = "dispatch_disabled"
REASON_INGESTION_DISABLED = "ingestion_disabled"
REASON_REWRITE_UNAVAILABLE = "rewrite_unavailable"

OPENROUTER_ERROR_CODES = frozenset(
    {
        REASON_OPENROUTER_KEYS_EXHAUSTED,
        REASON_OPENROUTER_RATE_LIMITED,
        REASON_OPENROUTER_PAYMENT_REQUIRED,
        REASON_OPENROUTER_AUTH_FAILED,
        REASON_OPENROUTER_NO_KEYS,
    }
)


def classify_openrouter_message(message: str) -> str:
    """Map OpenRouter / gRPC error text to an integration reason_code."""
    lower = message.lower()
    if "no openrouter keys" in lower or "openrouter_key" in lower:
        return REASON_OPENROUTER_NO_KEYS
    if any(
        token in lower
        for token in (
            "insufficient credit",
            "insufficient balance",
            "payment required",
            "billing",
            "purchase credits",
        )
    ):
        return REASON_OPENROUTER_PAYMENT_REQUIRED
    if "rate limit" in lower or "429" in lower:
        return REASON_OPENROUTER_RATE_LIMITED
    if any(token in lower for token in ("invalid api key", "unauthorized", "401", "403")):
        return REASON_OPENROUTER_AUTH_FAILED
    if "all openrouter keys exhausted" in lower or "keys exhausted" in lower:
        return REASON_OPENROUTER_KEYS_EXHAUSTED
    return REASON_OPENROUTER_KEYS_EXHAUSTED


def human_reason_message(reason_code: str, *, detail: str | None = None) -> str:
    messages = {
        REASON_OK: "Пайплайн работает штатно.",
        REASON_QUEUE_EMPTY: "Нет новых unconsumed черновиков — это норма.",
        REASON_PIPELINE_DEGRADED: "Есть сырьё в очереди, но черновики не создаются.",
        REASON_OPENROUTER_KEYS_EXHAUSTED: (
            "OpenRouter: все ключи исчерпаны — проверьте OPENROUTER_KEY_1..3 на rewrite."
        ),
        REASON_OPENROUTER_RATE_LIMITED: "OpenRouter: rate limit free-tier — подождите или добавьте ключ.",
        REASON_OPENROUTER_PAYMENT_REQUIRED: (
            "OpenRouter: закончились credits — пополните баланс или проверьте ключи."
        ),
        REASON_OPENROUTER_AUTH_FAILED: "OpenRouter: неверный API key — проверьте OPENROUTER_KEY_*.",
        REASON_OPENROUTER_NO_KEYS: "OpenRouter: ключи не заданы в env сервиса rewrite.",
        REASON_DISPATCH_DISABLED: "Dispatch выключен в Admin Settings (pipeline.dispatch_enabled).",
        REASON_INGESTION_DISABLED: "Ingestion выключен (pipeline.poll_enabled).",
        REASON_REWRITE_UNAVAILABLE: "scribely-rewrite недоступен по gRPC.",
    }
    base = messages.get(reason_code, "Пайплайн scribely: см. detail.")
    if detail:
        return f"{base} ({detail})"
    return base
