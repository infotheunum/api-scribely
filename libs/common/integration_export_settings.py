"""Admin-configurable defaults for theunum Export API freshness filters."""

from __future__ import annotations

from db.app_settings import get_setting
from sqlalchemy.orm import Session

DEFAULT_FRESHNESS_KEY = "integration.export.default_freshness"
DEFAULT_MAX_AGE_HOURS_KEY = "integration.export.default_max_age_hours"

DEFAULT_FRESHNESS_DESCRIPTION = (
    "Export API: default freshness when VPS omits query params — "
    "today (UTC midnight), 48h, or empty (no default filter)"
)
DEFAULT_MAX_AGE_HOURS_DESCRIPTION = (
    "Export API: default max_age_hours (1–168) when VPS omits query params; "
    "empty = not set. Combined with default_freshness — stricter cutoff wins."
)


def load_export_freshness_defaults(db: Session) -> tuple[str | None, int | None]:
    """Return (freshness_preset, max_age_hours) from AppSetting, or (None, None)."""
    raw_freshness = get_setting(db, DEFAULT_FRESHNESS_KEY, "")
    freshness: str | None = None
    if isinstance(raw_freshness, str) and raw_freshness in ("today", "48h"):
        freshness = raw_freshness

    raw_hours = get_setting(db, DEFAULT_MAX_AGE_HOURS_KEY, None)
    max_age_hours: int | None = None
    if raw_hours not in (None, ""):
        try:
            max_age_hours = int(raw_hours)
        except (TypeError, ValueError):
            max_age_hours = None
        else:
            if max_age_hours < 1 or max_age_hours > 168:
                max_age_hours = None

    return freshness, max_age_hours


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
