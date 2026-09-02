"""Token usage helpers for LLM provider responses and draft analytics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


EMPTY_USAGE = TokenUsage()


def parse_openai_compatible_usage(data: dict | None) -> TokenUsage:
    """OpenRouter / OpenAI Chat Completions `usage` object."""
    if not data or not isinstance(data, dict):
        return EMPTY_USAGE
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return EMPTY_USAGE
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def parse_anthropic_usage(data: dict | None) -> TokenUsage:
    """Anthropic Messages API `usage` object (input_tokens / output_tokens)."""
    if not data or not isinstance(data, dict):
        return EMPTY_USAGE
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return EMPTY_USAGE
    prompt = int(usage.get("input_tokens") or 0)
    completion = int(usage.get("output_tokens") or 0)
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )
