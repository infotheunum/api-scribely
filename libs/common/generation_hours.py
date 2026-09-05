"""Working-hours gate for article generation (poll → rewrite).

Defaults match editorial timezone (UTC+3 / Europe/Minsk): Mon–Fri
06:00–18:00 local; weekends and nights skip generation. Tunable via
AppSetting without redeploy (ТЗ §4.21).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db.app_settings import get_setting, set_setting
from sqlalchemy.orm import Session

# Master switch: when False, generation runs 24/7 (legacy behaviour).
ENABLED_KEY = "pipeline.generation_hours_enabled"
TIMEZONE_KEY = "pipeline.generation_timezone"
START_HOUR_KEY = "pipeline.generation_start_hour"
END_HOUR_KEY = "pipeline.generation_end_hour"
WEEKDAYS_ONLY_KEY = "pipeline.generation_weekdays_only"
WORKING_DAYS_KEY = "pipeline.generation_working_days"

DEFAULT_ENABLED = True
DEFAULT_TIMEZONE = "Europe/Minsk"
DEFAULT_START_HOUR = 6
DEFAULT_END_HOUR = 18
DEFAULT_WEEKDAYS_ONLY = True
DEFAULT_WORKING_DAYS = (0, 1, 2, 3, 4)

# Minsk has been permanently UTC+3 since 2011 (no DST).
_MINSK_FALLBACK = timezone(timedelta(hours=3), name="UTC+3")

_DESCRIPTIONS = {
    ENABLED_KEY: (
        "If true, poll/cluster/filter/dispatch/compliance run only inside "
        "selected working hours (see start/end/timezone/days). Archival & "
        "category sync keep running."
    ),
    TIMEZONE_KEY: "IANA timezone for generation window (default Europe/Minsk).",
    START_HOUR_KEY: "Local hour when generation starts (inclusive), 0–23.",
    END_HOUR_KEY: "Local hour when generation stops (exclusive), 1–24.",
    WEEKDAYS_ONLY_KEY: "Legacy fallback: if true, skip Saturday and Sunday entirely.",
    WORKING_DAYS_KEY: "JSON array of allowed weekdays where Mon=0 ... Sun=6.",
}


@dataclass(frozen=True, slots=True)
class GenerationHoursConfig:
    enabled: bool
    timezone_name: str
    start_hour: int
    end_hour: int
    working_days: tuple[int, ...]


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_hour(raw: Any, default: int) -> int:
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        return default
    if 0 <= hour <= 24:
        return hour
    return default


def _normalize_working_days(raw: Any) -> tuple[int, ...]:
    if raw is None or raw == "":
        return DEFAULT_WORKING_DAYS
    values: list[int] = []
    candidates: list[Any]
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("["):
            import json

            try:
                parsed = json.loads(cleaned)
            except ValueError:
                return DEFAULT_WORKING_DAYS
            if not isinstance(parsed, list):
                return DEFAULT_WORKING_DAYS
            candidates = parsed
        else:
            candidates = [part.strip() for part in cleaned.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        candidates = list(raw)
    else:
        return DEFAULT_WORKING_DAYS

    for item in candidates:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in values:
            values.append(day)
    return tuple(values) if values else DEFAULT_WORKING_DAYS


def resolve_tz(name: str) -> timezone | ZoneInfo:
    cleaned = (name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        if cleaned in {"Europe/Minsk", "UTC+3", "Etc/GMT-3"}:
            return _MINSK_FALLBACK
        return ZoneInfo("UTC")


def load_generation_hours(db: Session) -> GenerationHoursConfig:
    start = _as_hour(get_setting(db, START_HOUR_KEY, DEFAULT_START_HOUR), DEFAULT_START_HOUR)
    end = _as_hour(get_setting(db, END_HOUR_KEY, DEFAULT_END_HOUR), DEFAULT_END_HOUR)
    if end <= start:
        # Misconfigured window → fall back to defaults rather than never running.
        start, end = DEFAULT_START_HOUR, DEFAULT_END_HOUR
    working_days_raw = get_setting(db, WORKING_DAYS_KEY, None)
    if working_days_raw is None:
        weekdays_only = _as_bool(
            get_setting(db, WEEKDAYS_ONLY_KEY, DEFAULT_WEEKDAYS_ONLY),
            DEFAULT_WEEKDAYS_ONLY,
        )
        working_days = DEFAULT_WORKING_DAYS if weekdays_only else (0, 1, 2, 3, 4, 5, 6)
    else:
        working_days = _normalize_working_days(working_days_raw)
    return GenerationHoursConfig(
        enabled=_as_bool(get_setting(db, ENABLED_KEY, DEFAULT_ENABLED), DEFAULT_ENABLED),
        timezone_name=str(
            get_setting(db, TIMEZONE_KEY, DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
        ).strip()
        or DEFAULT_TIMEZONE,
        start_hour=start,
        end_hour=end,
        working_days=working_days,
    )


def is_within_generation_hours(
    config: GenerationHoursConfig,
    *,
    now: datetime | None = None,
) -> bool:
    """True when generation stages may run.

    Window is ``start_hour <= local_hour < end_hour``. With defaults that is
    Mon–Fri 06:00–17:59 Europe/Minsk. When ``enabled`` is False, always True.
    """
    if not config.enabled:
        return True

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(resolve_tz(config.timezone_name))

    if local.weekday() not in config.working_days:
        return False
    return config.start_hour <= local.hour < config.end_hour


def generation_allowed(db: Session, *, now: datetime | None = None) -> bool:
    return is_within_generation_hours(load_generation_hours(db), now=now)


def save_generation_hours(
    db: Session,
    *,
    enabled: bool,
    timezone_name: str,
    start_hour: int,
    end_hour: int,
    working_days: tuple[int, ...] | list[int],
    updated_by: uuid.UUID | None = None,
) -> GenerationHoursConfig:
    tz_name = (timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    # Validate timezone early (still allow Minsk fallback path via resolve_tz).
    resolve_tz(tz_name)

    start = max(0, min(23, int(start_hour)))
    end = max(1, min(24, int(end_hour)))
    if end <= start:
        raise ValueError("end_hour must be greater than start_hour")
    normalized_days = _normalize_working_days(working_days)

    values = {
        ENABLED_KEY: bool(enabled),
        TIMEZONE_KEY: tz_name,
        START_HOUR_KEY: start,
        END_HOUR_KEY: end,
        WEEKDAYS_ONLY_KEY: normalized_days == DEFAULT_WORKING_DAYS,
        WORKING_DAYS_KEY: list(normalized_days),
    }
    for key, value in values.items():
        set_setting(db, key, value, description=_DESCRIPTIONS[key], updated_by=updated_by)

    return GenerationHoursConfig(
        enabled=bool(enabled),
        timezone_name=tz_name,
        start_hour=start,
        end_hour=end,
        working_days=normalized_days,
    )


def generation_hours_as_dict(config: GenerationHoursConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "timezone": config.timezone_name,
        "start_hour": config.start_hour,
        "end_hour": config.end_hour,
        "working_days": list(config.working_days),
        "within_hours": is_within_generation_hours(config),
    }
