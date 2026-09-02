"""Direct Anthropic / OpenAI chat calls used as fallback after OpenRouter keys."""

from __future__ import annotations

import logging

import httpx

from common.integration_reasons import classify_openrouter_message
from rewrite_app.rewrite.openrouter_client import OpenRouterError

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# Cheap text models — Haiku / mini keep token cost low for rewrite JSON.
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

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
) -> tuple[str, str]:
    """Anthropic Messages API. Returns (raw_content, model_used)."""
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
    return str(content), model_used


def call_openai(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 90.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str, str]:
    """OpenAI Chat Completions. Returns (raw_content, model_used)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
    }
    try:
        response = httpx.post(OPENAI_URL, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        message = f"OpenAI HTTP {exc.response.status_code}: {body or exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc
    except httpx.HTTPError as exc:
        message = f"OpenAI request failed: {exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc

    data = response.json()
    if "error" in data:
        message = f"OpenAI error: {data['error']}"
        raise OpenRouterError(message, code=classify_openrouter_message(message))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        message = f"OpenAI unexpected response shape: {data}"
        raise OpenRouterError(message, code="unknown") from exc

    if content is None or not str(content).strip():
        raise OpenRouterError("OpenAI returned empty message content", code="unknown")

    model_used = data.get("model") or model
    return str(content), model_used
