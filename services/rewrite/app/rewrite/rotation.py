"""LLM provider rotation: per-article round-robin across paid primaries.

Qwen → OpenAI → Anthropic. OpenRouter is not in the cycle.
Fallback only when the assigned slot fails for this call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.integration_reasons import classify_openrouter_message
from common.token_usage import EMPTY_USAGE, TokenUsage
from db.app_settings import get_setting, set_setting
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

OPENROUTER_KEY_ALIASES = ["key_1", "key_2", "key_3"]
PRIMARY_ALIASES = ["qwen", "openai", "anthropic"]
# Legacy name — primary pool only (OpenRouter excluded from article RR).
FALLBACK_ALIASES = PRIMARY_ALIASES
KEY_ALIASES = PRIMARY_ALIASES + OPENROUTER_KEY_ALIASES

ROUND_ROBIN_INDEX_KEY = "llm.round_robin_index"
ROUND_ROBIN_INDEX_DESCRIPTION = (
    "Round-robin cursor over configured paid LLM slots (qwen/openai/anthropic). "
    "Advanced once per EnrichCluster; RewriteCluster reuses ClusterContext.llm_key_alias."
)

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
    """Reads the current rotation list from `LlmRotationModel` (ТЗ §4.21)."""
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
    """All primary provider slots failed for this call."""

    def __init__(self, message: str, *, code: str = "openrouter_keys_exhausted"):
        super().__init__(message)
        self.code = code


def configured_primaries(api_keys: dict[str, str]) -> list[str]:
    return [alias for alias in PRIMARY_ALIASES if (api_keys.get(alias) or "").strip()]


def pick_next_primary(db: Session, api_keys: dict[str, str]) -> str:
    """Advance global RR cursor and return the next configured primary alias."""
    primaries = configured_primaries(api_keys)
    if not primaries:
        raise AllKeysExhaustedError(
            "no paid LLM keys configured (QWEN_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY)",
            code="openrouter_no_keys_configured",
        )
    raw_index = get_setting(db, ROUND_ROBIN_INDEX_KEY, 0)
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        index = 0
    if index < 0:
        index = 0
    chosen = primaries[index % len(primaries)]
    set_setting(
        db,
        ROUND_ROBIN_INDEX_KEY,
        index + 1,
        description=ROUND_ROBIN_INDEX_DESCRIPTION,
    )
    db.commit()
    return chosen


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


def _ordered_primaries_from(
    start_alias: str,
    api_keys: dict[str, str],
) -> list[str]:
    primaries = configured_primaries(api_keys)
    if not primaries:
        return []
    if start_alias in primaries:
        start_idx = primaries.index(start_alias)
    else:
        start_idx = 0
    return primaries[start_idx:] + primaries[:start_idx]


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
    prefer_key_alias: str | None = None,
    advance: bool = False,
) -> tuple[str, str, str, TokenUsage]:
    """Call paid LLMs with per-article round-robin.

    - ``advance=True``: pick next primary (EnrichCluster) and try it first.
    - ``prefer_key_alias``: pin to that slot (RewriteCluster after enrich).
    - Fallback only after the current slot fails — then walk remaining primaries.
    - OpenRouter is not used.

    Returns (raw_content, key_alias_used, model_used, token_usage).
    """
    if prefer_key_alias and (api_keys.get(prefer_key_alias) or "").strip():
        start = prefer_key_alias
    elif advance:
        start = pick_next_primary(db, api_keys)
    else:
        # No pin / no advance — still start at next RR slot without double-advancing
        # when caller forgot flags; prefer configured order head.
        primaries = configured_primaries(api_keys)
        if not primaries:
            raise AllKeysExhaustedError(
                "no paid LLM keys configured",
                code="openrouter_no_keys_configured",
            )
        start = primaries[0]

    ordered = _ordered_primaries_from(start, api_keys)
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
            logger.warning("slot %s failed (failover if others left): %s", key_alias, exc)
            _record_usage(db, key_alias, _UNKNOWN_MODEL, success=False)
            db.commit()
            last_error = exc
            last_code = classify_openrouter_message(str(exc))
            continue

        _record_usage(db, key_alias, model_used, success=True)
        state = _get_or_create_state(db, key_alias)
        state.current_model_index = 0
        state.last_switched_at = datetime.now(UTC)
        db.commit()
        return content, key_alias, model_used, token_usage or EMPTY_USAGE

    raise AllKeysExhaustedError(
        str(last_error) if last_error else "no LLM keys configured",
        code=last_code if last_error else "openrouter_no_keys_configured",
    )
