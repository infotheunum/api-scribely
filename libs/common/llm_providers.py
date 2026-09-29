"""Admin-configurable primary LLM providers for article rotation (ТЗ §4.21)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from db.app_settings import get_setting, set_setting
from sqlalchemy.orm import Session

PrimaryProvider = Literal["qwen", "openai", "anthropic"]
ALLOWED_PROVIDERS: tuple[PrimaryProvider, ...] = ("qwen", "openai", "anthropic")
DEFAULT_ENABLED_PROVIDERS: tuple[PrimaryProvider, ...] = ("openai",)

ENABLED_PROVIDERS_KEY = "llm.enabled_providers"
ENABLED_PROVIDERS_DESCRIPTION = (
    "Primary LLM slots for article enrichment/rewrite/dedup confirmation — "
    'JSON array of qwen/openai/anthropic. Default ["openai"]. '
    "Round-robin runs only among enabled slots that have API keys in env."
)


def parse_enabled_providers(raw: Any) -> list[PrimaryProvider]:
    """Normalize AppSetting / form / env value to a non-empty provider list."""
    if raw is None or raw == "":
        return list(DEFAULT_ENABLED_PROVIDERS)
    values: list[str]
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("["):
            import json

            try:
                parsed = json.loads(cleaned)
            except ValueError:
                return list(DEFAULT_ENABLED_PROVIDERS)
            if not isinstance(parsed, list):
                return list(DEFAULT_ENABLED_PROVIDERS)
            values = [str(item).strip().lower() for item in parsed]
        else:
            values = [part.strip().lower() for part in cleaned.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        values = [str(item).strip().lower() for item in raw]
    else:
        return list(DEFAULT_ENABLED_PROVIDERS)

    ordered: list[PrimaryProvider] = []
    for alias in ALLOWED_PROVIDERS:
        if alias in values and alias not in ordered:
            ordered.append(alias)
    return ordered or list(DEFAULT_ENABLED_PROVIDERS)


def get_enabled_providers(db: Session) -> list[PrimaryProvider]:
    return parse_enabled_providers(
        get_setting(db, ENABLED_PROVIDERS_KEY, list(DEFAULT_ENABLED_PROVIDERS))
    )


def set_enabled_providers(
    db: Session,
    providers: list[str] | tuple[str, ...] | str,
    *,
    updated_by: uuid.UUID | None = None,
) -> list[PrimaryProvider]:
    normalized = parse_enabled_providers(providers)
    set_setting(
        db,
        ENABLED_PROVIDERS_KEY,
        list(normalized),
        description=ENABLED_PROVIDERS_DESCRIPTION,
        updated_by=updated_by,
    )
    return normalized
