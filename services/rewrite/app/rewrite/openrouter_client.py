from __future__ import annotations

import json
import logging
import re

import httpx

from common.integration_reasons import classify_openrouter_message

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class OpenRouterError(Exception):
    """A single key's call failed after OpenRouter exhausted its own
    per-key model fallback (ТЗ §4.5) — the Rotation Manager catches this
    to cascade to the next key."""

    def __init__(self, message: str, *, code: str = "unknown"):
        super().__init__(message)
        self.code = code


def extract_json(content: str) -> dict:
    """Free models routinely wrap JSON in ```json fences despite
    instructions not to — stripped here rather than treated as a parse
    failure, since that would trigger a wasted regenerate for a purely
    cosmetic issue."""
    if not content or not content.strip():
        raise ValueError("empty LLM response content")
    cleaned = _JSON_FENCE.sub("", content.strip())
    return json.loads(cleaned)


def call_openrouter(
    *,
    api_key: str,
    models: list[str],
    system_prompt: str,
    user_prompt: str,
    timeout: float = 90.0,
) -> tuple[str, str]:
    """One call to OpenRouter with the free-model fallback list (ТЗ
    §4.5) — OpenRouter itself retries across `models` on rate-limit/
    moderation/context/downtime errors, no extra code needed for that
    part. Returns (raw_content, model_actually_used). Raises
    OpenRouterError once the whole list is exhausted for this key."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "models": models,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        message = f"HTTP {exc.response.status_code}: {body or exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc
    except httpx.HTTPError as exc:
        message = f"request failed: {exc}"
        raise OpenRouterError(message, code=classify_openrouter_message(message)) from exc

    data = response.json()
    if "error" in data:
        err = data["error"]
        message = f"OpenRouter error: {err}"
        raise OpenRouterError(message, code=classify_openrouter_message(message))
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        message = f"unexpected response shape: {data}"
        raise OpenRouterError(message, code="unknown") from exc

    if content is None or not str(content).strip():
        message = "OpenRouter returned empty message content"
        raise OpenRouterError(message, code="unknown")

    model_used = data.get("model") or models[0]
    return str(content), model_used
