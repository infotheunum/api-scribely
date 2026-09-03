"""Direct Anthropic / OpenAI / Qwen (DashScope) chat calls as OpenRouter fallbacks."""

from __future__ import annotations

import logging

import httpx
from common.integration_reasons import classify_openrouter_message
from common.token_usage import TokenUsage, parse_anthropic_usage, parse_openai_compatible_usage
from rewrite_app.rewrite.openrouter_client import OpenRouterError

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# DashScope OpenAI-compatible (intl). CN: dashscope.aliyuncs.com
DEFAULT_QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# Cheap text models — Haiku / mini / qwen-plus keep token cost low for rewrite JSON.
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_QWEN_MODEL = "qwen-plus"

# Cap completion size: rewrite JSON is ~2–4k tokens max; lower = cheaper.
DEFAULT_MAX_TOKENS = 4096


def call_anthropic(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 90.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str, str, TokenUsage]:
    """Anthropic Messages API. Returns (raw_content, model_used, token_usage)."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    try:
        response = httpx.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        message = f"Anthropic HTTP {exc.response.status_code}: {body or exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc
    except httpx.HTTPError as exc:
        message = f"Anthropic request failed: {exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc

    data = response.json()
    if data.get("type") == "error" or "error" in data:
        message = f"Anthropic error: {data.get('error', data)}"
        raise OpenRouterError(message, code=classify_openrouter_message(message))

    try:
        blocks = data["content"]
        text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        content = "".join(text_parts)
    except (KeyError, TypeError, AttributeError) as exc:
        message = f"Anthropic unexpected response shape: {data}"
        raise OpenRouterError(message, code="unknown") from exc

    if not content or not str(content).strip():
        raise OpenRouterError("Anthropic returned empty message content", code="unknown")

    model_used = data.get("model") or model
    return str(content), model_used, parse_anthropic_usage(data)


def call_openai_compatible(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    base_url: str,
    provider_label: str,
    timeout: float = 90.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    json_object: bool = True,
) -> tuple[str, str, TokenUsage]:
    """OpenAI-compatible Chat Completions (OpenAI, DashScope/Qwen, …)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        message = f"{provider_label} HTTP {exc.response.status_code}: {body or exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc
    except httpx.HTTPError as exc:
        message = f"{provider_label} request failed: {exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc

    data = response.json()
    if "error" in data:
        message = f"{provider_label} error: {data['error']}"
        raise OpenRouterError(message, code=classify_openrouter_message(message))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        message = f"{provider_label} unexpected response shape: {data}"
        raise OpenRouterError(message, code="unknown") from exc

    if content is None or not str(content).strip():
        raise OpenRouterError(
            f"{provider_label} returned empty message content",
            code="unknown",
        )

    model_used = data.get("model") or model
    return str(content), model_used, parse_openai_compatible_usage(data)


def call_openai(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 90.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str, str, TokenUsage]:
    """OpenAI Chat Completions. Returns (raw_content, model_used, token_usage)."""
    return call_openai_compatible(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        base_url=OPENAI_URL.rsplit("/chat/completions", 1)[0],
        provider_label="OpenAI",
        timeout=timeout,
        max_tokens=max_tokens,
    )


def call_qwen(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    base_url: str = DEFAULT_QWEN_BASE_URL,
    timeout: float = 90.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str, str, TokenUsage]:
    """Qwen via DashScope OpenAI-compatible API."""
    return call_openai_compatible(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        base_url=base_url or DEFAULT_QWEN_BASE_URL,
        provider_label="Qwen",
        timeout=timeout,
        max_tokens=max_tokens,
    )
