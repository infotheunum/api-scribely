from __future__ import annotations

from common.rewrite_body_limits import BODY_MAX_CHARS, BODY_MIN_CHARS

# Machine-readable codes returned to api.theunum.io cron (integrations API).

REASON_OK = "ok"
REASON_QUEUE_EMPTY = "queue_empty"
REASON_PIPELINE_DEGRADED = "pipeline_degraded"
REASON_OPENROUTER_KEYS_EXHAUSTED = "openrouter_keys_exhausted"
REASON_OPENROUTER_RATE_LIMITED = "openrouter_rate_limited"
REASON_OPENROUTER_PAYMENT_REQUIRED = "openrouter_payment_required"
REASON_OPENROUTER_AUTH_FAILED = "openrouter_auth_failed"
REASON_OPENROUTER_NO_KEYS = "openrouter_no_keys_configured"
REASON_REWRITE_VALIDATION_FAILED = "rewrite_validation_failed"
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

_REASON_PREFIX = "[reason="


def format_integration_error(code: str, message: str) -> str:
    """Embed machine-readable reason in gRPC/HTTP error text (rewrite → worker)."""
    return f"{_REASON_PREFIX}{code}] {message}"


def parse_integration_error_detail(message: str) -> tuple[str | None, str]:
    if not message.startswith(_REASON_PREFIX):
        return None, message
    try:
        end = message.index("]", len(_REASON_PREFIX))
    except ValueError:
        return None, message
    code = message[len(_REASON_PREFIX) : end]
    rest = message[end + 1 :].lstrip()
    return code or None, rest


def resolve_integration_error_code(message: str) -> str:
    """Prefer explicit [reason=code] from rewrite; else classify free text."""
    code, body = parse_integration_error_detail(message)
    if code:
        return code
    return classify_openrouter_message(body or message)


def classify_openrouter_message(message: str) -> str:
    """Map OpenRouter / gRPC error text to an integration reason_code."""
    lower = message.lower()
    if any(
        token in lower
        for token in (
            "validation error",
            "rewritecluster failed after",
            "enrichcluster failed after",
            "body_en must",
            "body_ru must",
            "value error",
        )
    ):
        return REASON_REWRITE_VALIDATION_FAILED
    if "no openrouter keys" in lower or "openrouter_key" in lower:
        return REASON_OPENROUTER_NO_KEYS
    if "402" in lower or any(
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
    if any(token in lower for token in ("timeout", "timed out", "connect", "502", "503", "504")):
        return REASON_OPENROUTER_KEYS_EXHAUSTED
    # Unknown dispatch/LLM text — degraded, not "keys exhausted" (that false
    # positive hid body-length ValidationError as keys_exhausted in prod).
    return REASON_PIPELINE_DEGRADED


def human_reason_message(reason_code: str, *, detail: str | None = None) -> str:
    messages = {
        REASON_OK: "Пайплайн работает штатно.",
        REASON_QUEUE_EMPTY: "Нет новых unconsumed черновиков — это норма.",
        REASON_PIPELINE_DEGRADED: "Есть сырьё в очереди, но черновики не создаются.",
        REASON_REWRITE_VALIDATION_FAILED: (
            "LLM вернул черновик, который не прошёл валидацию "
            f"(длина body {BODY_MIN_CHARS}–{BODY_MAX_CHARS} символов, формат). "
            "Кластер уйдёт в retry."
        ),
        REASON_OPENROUTER_KEYS_EXHAUSTED: (
            "Все LLM-слоты исчерпаны — проверьте OPENROUTER_KEY_1..3, "
            "ANTHROPIC_API_KEY и OPENAI_API_KEY на rewrite."
        ),
        REASON_OPENROUTER_RATE_LIMITED: "OpenRouter: rate limit free-tier — подождите или добавьте ключ.",
        REASON_OPENROUTER_PAYMENT_REQUIRED: (
            "OpenRouter: закончились credits — пополните баланс или проверьте ключи "
            "(есть фолбэк Anthropic/OpenAI, если заданы)."
        ),
        REASON_OPENROUTER_AUTH_FAILED: "LLM auth failed — проверьте OPENROUTER_KEY_* / ANTHROPIC / OPENAI.",
        REASON_OPENROUTER_NO_KEYS: (
            "LLM-ключи не заданы в env сервиса rewrite "
            "(OPENROUTER_KEY_1..3 / ANTHROPIC_API_KEY / OPENAI_API_KEY)."
        ),
        REASON_DISPATCH_DISABLED: "Dispatch выключен в Admin Settings (pipeline.dispatch_enabled).",
        REASON_INGESTION_DISABLED: "Ingestion выключен (pipeline.poll_enabled).",
        REASON_REWRITE_UNAVAILABLE: "scribely-rewrite недоступен по gRPC.",
    }
    base = messages.get(reason_code, "Пайплайн scribely: см. detail.")
    if detail:
        return f"{base} ({detail})"
    return base
