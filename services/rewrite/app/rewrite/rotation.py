from __future__ import annotations

import logging
from datetime import UTC, datetime

from db.models import LlmRotationModel, LLMRotationState, LLMRotationUsage
from rewrite_app.rewrite.openrouter_client import OpenRouterError, call_openrouter
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KEY_ALIASES = ["key_1", "key_2", "key_3"]

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
    """All 3 keys failed — ТЗ §4.5 point 4: caller's job is to not lose
    the task, not to retry here. Since a cluster without a Draft yet
    stays selectable by Phase 3's queue, the next scheduler tick is the
    de-facto deferred retry queue — no separate infrastructure needed."""


def _current_key_alias(db: Session) -> str:
    switched = [s for s in db.scalars(select(LLMRotationState)) if s.last_switched_at is not None]
    if not switched:
        return KEY_ALIASES[0]
    return max(switched, key=lambda s: s.last_switched_at).key_alias


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


def call_with_rotation(
    db: Session,
    *,
    api_keys: dict[str, str],
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, str, str]:
    """Calls OpenRouter, cascading across the 3 keys (persisted "sticky"
    starting point, ТЗ §4.5 point 5) when one is exhausted. Returns
    (raw_content, key_alias_used, model_used)."""
    start = _current_key_alias(db)
    start_idx = KEY_ALIASES.index(start)
    ordered = KEY_ALIASES[start_idx:] + KEY_ALIASES[:start_idx]
    free_models = active_free_models(db)

    last_error: Exception | None = None
    for key_alias in ordered:
        api_key = api_keys.get(key_alias)
        if not api_key:
            continue
        try:
            content, model_used = call_openrouter(
                api_key=api_key,
                models=free_models,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except OpenRouterError as exc:
            logger.warning("key %s exhausted: %s", key_alias, exc)
            _record_usage(db, key_alias, _UNKNOWN_MODEL, success=False)
            db.commit()
            last_error = exc
            continue

        _record_usage(db, key_alias, model_used, success=True)
        state = _get_or_create_state(db, key_alias)
        state.current_model_index = (
            free_models.index(model_used) if model_used in free_models else 0
        )
        if key_alias != start:
            # only a real key-switch (not the sticky default) needs a
            # fresh timestamp — keeps _current_key_alias() pointed at
            # whichever key most recently proved itself working.
            state.last_switched_at = datetime.now(UTC)
        db.commit()
        return content, key_alias, model_used

    raise AllKeysExhaustedError(str(last_error))
