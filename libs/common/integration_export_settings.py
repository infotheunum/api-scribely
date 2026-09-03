"""Admin-configurable defaults for theunum Export API list filters."""

from __future__ import annotations

import uuid
from typing import Any

from db.app_settings import get_setting, set_setting
from sqlalchemy.orm import Session

DEFAULT_FRESHNESS_KEY = "integration.export.default_freshness"
DEFAULT_MAX_AGE_HOURS_KEY = "integration.export.default_max_age_hours"
DEFAULT_LIMIT_KEY = "integration.export.default_limit"

DEFAULT_FRESHNESS_DESCRIPTION = (
    "Export API: default freshness when VPS omits query params — "
    "today (AI rewrite since UTC midnight), 48h (draft created in last 48h), "
    "or empty (no default filter)"
)
DEFAULT_MAX_AGE_HOURS_DESCRIPTION = (
    "Export API: default max_age_hours (1–168) when VPS omits query params; "
    "empty = not set. Combined with default_freshness — stricter cutoff wins."
)
DEFAULT_LIMIT_DESCRIPTION = (
    "Export API: default limit (1–100) when VPS omits limit query param; "
    "empty = API default 50"
)

FALLBACK_LIST_LIMIT = 50


def _parse_freshness(raw: Any) -> str | None:
    if isinstance(raw, str) and raw in ("today", "48h"):
        return raw
    return None


def _parse_max_age_hours(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= hours <= 168:
        return hours
    return None


def _parse_limit(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= limit <= 100:
        return limit
    return None


def load_export_defaults(db: Session) -> dict[str, Any]:
    """Current admin defaults for Export API (None = unset)."""
    freshness, max_age_hours = load_export_freshness_defaults(db)
    return {
        "default_freshness": freshness or "",
        "default_max_age_hours": max_age_hours,
        "default_limit": _parse_limit(get_setting(db, DEFAULT_LIMIT_KEY, None)),
    }


def load_export_freshness_defaults(db: Session) -> tuple[str | None, int | None]:
    """Return (freshness_preset, max_age_hours) from AppSetting, or (None, None)."""
    return (
        _parse_freshness(get_setting(db, DEFAULT_FRESHNESS_KEY, "")),
        _parse_max_age_hours(get_setting(db, DEFAULT_MAX_AGE_HOURS_KEY, None)),
    )


def load_export_limit_default(db: Session) -> int:
    """Return admin default limit or API fallback 50."""
    parsed = _parse_limit(get_setting(db, DEFAULT_LIMIT_KEY, None))
    return parsed if parsed is not None else FALLBACK_LIST_LIMIT


def save_export_defaults(
    db: Session,
    *,
    default_freshness: str = "",
    default_max_age_hours: int | None = None,
    default_limit: int | None = None,
    updated_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Persist export admin defaults; returns normalized values."""
    freshness_value = default_freshness.strip()
    if freshness_value and freshness_value not in ("today", "48h"):
        freshness_value = ""

    hours_value: str | int = ""
    if default_max_age_hours is not None:
        hours_value = max(1, min(168, int(default_max_age_hours)))

    limit_value: str | int = ""
    if default_limit is not None:
        limit_value = max(1, min(100, int(default_limit)))

    set_setting(
        db,
        DEFAULT_FRESHNESS_KEY,
        freshness_value,
        description=DEFAULT_FRESHNESS_DESCRIPTION,
        updated_by=updated_by,
    )
    set_setting(
        db,
        DEFAULT_MAX_AGE_HOURS_KEY,
        hours_value,
        description=DEFAULT_MAX_AGE_HOURS_DESCRIPTION,
        updated_by=updated_by,
    )
    set_setting(
        db,
        DEFAULT_LIMIT_KEY,
        limit_value,
        description=DEFAULT_LIMIT_DESCRIPTION,
        updated_by=updated_by,
    )
    return load_export_defaults(db)


def merge_export_freshness_query(
    db: Session,
    *,
    generated_since,
    freshness,
    max_age_hours,
) -> tuple[object, object, object, str]:
    """Apply admin defaults when the request did not specify any freshness filter.

    Returns (generated_since, freshness, max_age_hours, source) where source is
    query | admin_default | none.
    """
    if generated_since is not None or freshness is not None or max_age_hours is not None:
        return generated_since, freshness, max_age_hours, "query"

    default_freshness, default_max_age = load_export_freshness_defaults(db)
    if default_freshness is None and default_max_age is None:
        return None, None, None, "none"

    return generated_since, default_freshness, default_max_age, "admin_default"


def merge_export_limit_query(db: Session, *, limit: int | None) -> tuple[int, str]:
    """Apply admin default limit when query omitted limit."""
    if limit is not None:
        return limit, "query"
    admin_limit = _parse_limit(get_setting(db, DEFAULT_LIMIT_KEY, None))
    if admin_limit is not None:
        return admin_limit, "admin_default"
    return FALLBACK_LIST_LIMIT, "api_default"
