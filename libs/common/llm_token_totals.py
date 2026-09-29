"""Persist lifetime LLM token counters in AppSetting for Export /status."""

from __future__ import annotations

from db.app_settings import get_setting, set_setting
from sqlalchemy.orm import Session

from common.token_usage import TokenUsage

KEY_PROMPT_TOTAL = "llm.tokens.prompt_total"
KEY_COMPLETION_TOTAL = "llm.tokens.completion_total"
KEY_TOTAL = "llm.tokens.total"
KEY_CALLS_TOTAL = "llm.tokens.calls_total"

KEY_DEDUP_PROMPT_TOTAL = "llm.tokens.dedup.prompt_total"
KEY_DEDUP_COMPLETION_TOTAL = "llm.tokens.dedup.completion_total"
KEY_DEDUP_TOTAL = "llm.tokens.dedup.total"
KEY_DEDUP_CALLS_TOTAL = "llm.tokens.dedup.calls_total"


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_token_totals(db: Session) -> dict[str, int]:
    return {
        "prompt_tokens": _as_int(get_setting(db, KEY_PROMPT_TOTAL, 0)),
        "completion_tokens": _as_int(get_setting(db, KEY_COMPLETION_TOTAL, 0)),
        "total_tokens": _as_int(get_setting(db, KEY_TOTAL, 0)),
        "calls": _as_int(get_setting(db, KEY_CALLS_TOTAL, 0)),
        "dedup_prompt_tokens": _as_int(get_setting(db, KEY_DEDUP_PROMPT_TOTAL, 0)),
        "dedup_completion_tokens": _as_int(get_setting(db, KEY_DEDUP_COMPLETION_TOTAL, 0)),
        "dedup_total_tokens": _as_int(get_setting(db, KEY_DEDUP_TOTAL, 0)),
        "dedup_calls": _as_int(get_setting(db, KEY_DEDUP_CALLS_TOTAL, 0)),
    }


def record_token_usage(
    db: Session,
    usage: TokenUsage,
    *,
    calls: int = 1,
    bucket: str = "article",
) -> dict[str, int]:
    """Atomically bump lifetime totals; returns new totals.

    ``bucket="dedup"`` also increments dedup-specific counters (ConfirmDuplicate).
    All buckets still feed the global totals so /status matches provider bills.
    """
    current = load_token_totals(db)
    prompt = current["prompt_tokens"] + max(0, usage.prompt_tokens)
    completion = current["completion_tokens"] + max(0, usage.completion_tokens)
    total = current["total_tokens"] + max(0, usage.total_tokens)
    call_count = current["calls"] + max(0, calls)
    set_setting(db, KEY_PROMPT_TOTAL, prompt, description="Lifetime LLM prompt tokens")
    set_setting(db, KEY_COMPLETION_TOTAL, completion, description="Lifetime LLM completion tokens")
    set_setting(db, KEY_TOTAL, total, description="Lifetime LLM total tokens")
    set_setting(db, KEY_CALLS_TOTAL, call_count, description="Lifetime successful LLM calls")

    dedup_prompt = current["dedup_prompt_tokens"]
    dedup_completion = current["dedup_completion_tokens"]
    dedup_total = current["dedup_total_tokens"]
    dedup_calls = current["dedup_calls"]
    if bucket == "dedup":
        dedup_prompt += max(0, usage.prompt_tokens)
        dedup_completion += max(0, usage.completion_tokens)
        dedup_total += max(0, usage.total_tokens)
        dedup_calls += max(0, calls)
        set_setting(
            db,
            KEY_DEDUP_PROMPT_TOTAL,
            dedup_prompt,
            description="Lifetime ConfirmDuplicate prompt tokens",
        )
        set_setting(
            db,
            KEY_DEDUP_COMPLETION_TOTAL,
            dedup_completion,
            description="Lifetime ConfirmDuplicate completion tokens",
        )
        set_setting(
            db,
            KEY_DEDUP_TOTAL,
            dedup_total,
            description="Lifetime ConfirmDuplicate total tokens",
        )
        set_setting(
            db,
            KEY_DEDUP_CALLS_TOTAL,
            dedup_calls,
            description="Lifetime ConfirmDuplicate LLM calls",
        )

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "calls": call_count,
        "dedup_prompt_tokens": dedup_prompt,
        "dedup_completion_tokens": dedup_completion,
        "dedup_total_tokens": dedup_total,
        "dedup_calls": dedup_calls,
    }
