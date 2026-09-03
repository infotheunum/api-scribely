from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.integration_reasons import classify_openrouter_message
from common.token_usage import EMPTY_USAGE, TokenUsage
from db.models import LlmRotationModel, LLMRotationState, LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError, call_openrouter
from rewrite_app.rewrite.provider_clients import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_QWEN_BASE_URL,
    DEFAULT_QWEN_MODEL,
    call_anthropic,
    call_openai,
    call_qwen,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Paid providers first (OpenRouter free keys often exhausted / dead).
# Sticky round-robin across the whole list (ТЗ §4.5 + provider fallback).
OPENROUTER_KEY_ALIASES = ["key_1", "key_2", "key_3"]
PRIMARY_ALIASES = ["qwen", "openai", "anthropic"]
KEY_ALIASES = PRIMARY_ALIASES + OPENROUTER_KEY_ALIASES
# Back-compat name used in docs/comments.
FALLBACK_ALIASES = PRIMARY_ALIASES

# Fixed 2026-08-03 (ТЗ §8.2 open question, resolved in Фаза 4) —
# live-verified against GET https://openrouter.ai/api/v1/models the same
# day: 14 models carried the :free suffix. Of the general-purpose text
# ones (excluding code/vision/safety-classifier specialists and
# providers with no track record for prose), these 3 — capped at exactly
# 3 because OpenRouter rejects `models` arrays longer than that on this
# endpoint too (confirmed live: "'models' array must have 3 items or
# fewer", not just on the Anthropic-compatible endpoint the ТЗ's
# research flagged as the known limit, ТЗ §4.5). Seed data for the
# `LlmRotationModel` table (ТЗ §4.21, Фаза 5) — edit the rotation list
# through Admin Settings from here on, not this constant.
FREE_MODELS = [
    "openai/gpt-oss-20b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

_UNKNOWN_MODEL = "<exhausted-before-response>"


def _seed_default_models(db: Session) -> list[LlmRotationModel]:
    models = [
        LlmRotationModel(model_id=model_id, position=i, is_active=True)
        for i, model_id in enumerate(FREE_MODELS)
    ]
    db.add_all(models)
    db.flush()
    return models


def active_free_models(db: Session) -> list[str]:
    """Reads the current rotation list from `LlmRotationModel` (ТЗ
    §4.21), bootstrapping it from FREE_MODELS the first time the table
    is touched (same self-heal pattern as PromptVersion/Topic). Falls
    back to FREE_MODELS if the table exists but every row was
    deactivated — an empty `models` list would break every call, and
    unlike Topic there's already a dedicated `pipeline.dispatch_enabled`
    kill-switch for "pause everything", so this isn't a valid admin
    state to honor silently."""
    rows = db.scalars(
        select(LlmRotationModel)
        .where(LlmRotationModel.is_active.is_(True))
        .order_by(LlmRotationModel.position)
    ).all()
    if not rows:
        if db.scalars(select(LlmRotationModel)).first() is None:
            rows = _seed_default_models(db)
            db.commit()
        else:
            logger.warning("no active LlmRotationModel rows — falling back to FREE_MODELS")
            return list(FREE_MODELS)
    return [row.model_id for row in rows]


class AllKeysExhaustedError(Exception):
    """All provider slots failed — ТЗ §4.5 point 4: caller's job is to not lose
    the task, not to retry here. Since a cluster without a Draft yet
    stays selectable by Phase 3's queue, the next scheduler tick is the
    de-facto deferred retry queue — no separate infrastructure needed."""

    def __init__(self, message: str, *, code: str = "openrouter_keys_exhausted"):
        super().__init__(message)
        self.code = code


def _current_key_alias(db: Session) -> str:
    switched = [s for s in db.scalars(select(LLMRotationState)) if s.last_switched_at is not None]
    if not switched:
        return KEY_ALIASES[0]
    last = max(switched, key=lambda s: s.last_switched_at).key_alias
    return last if last in KEY_ALIASES else KEY_ALIASES[0]


def _get_or_create_state(db: Session, key_alias: str) -> LLMRotationState:
    state = db.get(LLMRotationState, key_alias)
    if state is None:
        state = LLMRotationState(key_alias=key_alias, current_model_index=0)
        db.add(state)
    return state


def _record_usage(db: Session, key_alias: str, model: str, *, success: bool) -> None:
    usage = db.get(LLMRotationUsage, (key_alias, model))
    if usage is None:
        usage = LLMRotationUsage(key_alias=key_alias, model=model, usage_count=0, error_count=0)
        db.add(usage)
    if success:
        usage.usage_count += 1
    else:
        usage.error_count += 1


def _call_slot(
    *,
    key_alias: str,
    api_key: str,
    free_models: list[str],
    system_prompt: str,
    user_prompt: str,
    anthropic_model: str,
    openai_model: str,
    qwen_model: str,
    qwen_base_url: str,
) -> tuple[str, str, TokenUsage]:
    """Dispatch one rotation slot to the right provider client."""
    if key_alias in OPENROUTER_KEY_ALIASES:
        return call_openrouter(
            api_key=api_key,
            models=free_models,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    if key_alias == "anthropic":
        return call_anthropic(
            api_key=api_key,
            model=anthropic_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    if key_alias == "openai":
        return call_openai(
            api_key=api_key,
            model=openai_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    if key_alias == "qwen":
        return call_qwen(
            api_key=api_key,
            model=qwen_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            base_url=qwen_base_url,
        )
    raise OpenRouterError(f"unknown provider slot: {key_alias}", code="unknown")


def call_with_rotation(
    db: Session,
    *,
    api_keys: dict[str, str],
    system_prompt: str,
    user_prompt: str,
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL,
    openai_model: str = DEFAULT_OPENAI_MODEL,
    qwen_model: str = DEFAULT_QWEN_MODEL,
    qwen_base_url: str = DEFAULT_QWEN_BASE_URL,
) -> tuple[str, str, str, TokenUsage]:
    """Calls LLM providers in sticky round-robin:

    1. Qwen / DashScope (qwen-plus by default)
    2. OpenAI (gpt-4o-mini by default)
    3. Anthropic (Haiku by default)
    4. OpenRouter key_1 → key_2 → key_3 (free models; last resort)

    On failure of a slot, cascades to the next; successful slot becomes
    sticky start for the next call. Returns
    (raw_content, key_alias_used, model_used, token_usage).
    """
    start = _current_key_alias(db)
    # Don't sticky-start on OpenRouter if any paid primary key is set —
    # free OR slots are often exhausted and would burn 3 failed calls first.
    if start in OPENROUTER_KEY_ALIASES and any(
        (api_keys.get(alias) or "").strip() for alias in PRIMARY_ALIASES
    ):
        start = PRIMARY_ALIASES[0]
    start_idx = KEY_ALIASES.index(start) if start in KEY_ALIASES else 0
    ordered = KEY_ALIASES[start_idx:] + KEY_ALIASES[:start_idx]
    free_models = active_free_models(db)

    last_error: Exception | None = None
    last_code = "openrouter_keys_exhausted"
    for key_alias in ordered:
        api_key = (api_keys.get(key_alias) or "").strip()
        if not api_key:
            continue
        try:
            content, model_used, token_usage = _call_slot(
                key_alias=key_alias,
                api_key=api_key,
                free_models=free_models,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                anthropic_model=anthropic_model,
                openai_model=openai_model,
                qwen_model=qwen_model,
                qwen_base_url=qwen_base_url,
            )
        except OpenRouterError as exc:
            logger.warning("slot %s exhausted: %s", key_alias, exc)
            _record_usage(db, key_alias, _UNKNOWN_MODEL, success=False)
            db.commit()
            last_error = exc
            last_code = classify_openrouter_message(str(exc))
            continue

        _record_usage(db, key_alias, model_used, success=True)
        state = _get_or_create_state(db, key_alias)
        if key_alias in OPENROUTER_KEY_ALIASES:
            state.current_model_index = (
                free_models.index(model_used) if model_used in free_models else 0
            )
        else:
            state.current_model_index = 0
        if key_alias != start:
            # only a real key-switch (not the sticky default) needs a
            # fresh timestamp — keeps _current_key_alias() pointed at
            # whichever key most recently proved itself working.
            state.last_switched_at = datetime.now(UTC)
        db.commit()
        return content, key_alias, model_used, token_usage or EMPTY_USAGE

    raise AllKeysExhaustedError(
        str(last_error) if last_error else "no LLM keys configured",
        code=last_code if last_error else "openrouter_no_keys_configured",
    )
