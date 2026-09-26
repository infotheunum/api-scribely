"""Per-day generation windows for poll → rewrite.

Defaults (Europe/Minsk):
- Mon–Fri 06:00–18:00
- Sat–Sun 02:00–09:00 (night→morning), then full pause
- Weekend daily draft cap 25
- Admin can request a manual burst (e.g. +25) outside the window

Tunable via AppSetting / Admin UI without redeploy (ТЗ §4.21).
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
# Legacy flat window keys — still read as migration fallback.
START_HOUR_KEY = "pipeline.generation_start_hour"
END_HOUR_KEY = "pipeline.generation_end_hour"
WEEKDAYS_ONLY_KEY = "pipeline.generation_weekdays_only"
WORKING_DAYS_KEY = "pipeline.generation_working_days"
# Per-day schedule: {"0":{"enabled":true,"start":6,"end":18}, ...}
SCHEDULE_KEY = "pipeline.generation_schedule"
# One-shot admin burst outside the schedule window.
MANUAL_BURST_KEY = "pipeline.manual_generation_burst"

WEEKDAY_DAILY_LIMIT_KEY = "queue.daily_limit"
WEEKEND_DAILY_LIMIT_KEY = "queue.weekend_daily_limit"

DEFAULT_ENABLED = True
DEFAULT_TIMEZONE = "Europe/Minsk"
DEFAULT_WEEKDAY_START = 6
DEFAULT_WEEKDAY_END = 18
DEFAULT_WEEKEND_START = 2
DEFAULT_WEEKEND_END = 9
DEFAULT_WEEKDAY_DAILY_LIMIT = 100
DEFAULT_WEEKEND_DAILY_LIMIT = 25
DEFAULT_WORKING_DAYS = (0, 1, 2, 3, 4)
DEFAULT_MANUAL_BURST_QUOTA = 25
DEFAULT_MANUAL_BURST_TTL_HOURS = 3

DAY_LABELS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Minsk has been permanently UTC+3 since 2011 (no DST).
_MINSK_FALLBACK = timezone(timedelta(hours=3), name="UTC+3")

_DESCRIPTIONS = {
    ENABLED_KEY: (
        "If true, poll/cluster/filter/dispatch/compliance run only inside "
        "the per-day schedule (or during an active manual burst). "
        "Archival & category sync keep running."
    ),
    TIMEZONE_KEY: "IANA timezone for generation windows (default Europe/Minsk).",
    START_HOUR_KEY: "Legacy flat start hour (migrated into schedule when absent).",
    END_HOUR_KEY: "Legacy flat end hour (migrated into schedule when absent).",
    WEEKDAYS_ONLY_KEY: "Legacy fallback: if true, skip Saturday and Sunday entirely.",
    WORKING_DAYS_KEY: "Legacy JSON array of allowed weekdays where Mon=0 ... Sun=6.",
    SCHEDULE_KEY: (
        "Per-day generation windows: "
        '{"0":{"enabled":true,"start":6,"end":18},...} Mon=0 … Sun=6.'
    ),
    WEEKEND_DAILY_LIMIT_KEY: (
        "Max drafts created on Sat/Sun during the scheduled morning window "
        "(editorial day, Europe/Minsk). Weekdays use queue.daily_limit."
    ),
    MANUAL_BURST_KEY: (
        "Active admin-requested generation burst: "
        '{"quota":25,"created":0,"expires_at":"...","requested_at":"..."}.'
    ),
}


@dataclass(frozen=True, slots=True)
class DayWindow:
    enabled: bool
    start_hour: int
    end_hour: int


@dataclass(frozen=True, slots=True)
class GenerationHoursConfig:
    enabled: bool
    timezone_name: str
    days: tuple[DayWindow, ...]  # length 7, index = weekday Mon=0
    weekend_daily_limit: int

    @property
    def working_days(self) -> tuple[int, ...]:
        return tuple(i for i, day in enumerate(self.days) if day.enabled)

    @property
    def start_hour(self) -> int:
        """Representative weekday start (for legacy API consumers)."""
        for i in range(5):
            if self.days[i].enabled:
                return self.days[i].start_hour
        return DEFAULT_WEEKDAY_START

    @property
    def end_hour(self) -> int:
        for i in range(5):
            if self.days[i].enabled:
                return self.days[i].end_hour
        return DEFAULT_WEEKDAY_END


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


def _as_positive_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def default_day_window(weekday: int) -> DayWindow:
    if weekday >= 5:
        return DayWindow(True, DEFAULT_WEEKEND_START, DEFAULT_WEEKEND_END)
    return DayWindow(True, DEFAULT_WEEKDAY_START, DEFAULT_WEEKDAY_END)


def default_schedule() -> tuple[DayWindow, ...]:
    return tuple(default_day_window(i) for i in range(7))


def _normalize_day_window(raw: Any, *, weekday: int) -> DayWindow:
    fallback = default_day_window(weekday)
    if not isinstance(raw, dict):
        return fallback
    enabled = _as_bool(raw.get("enabled", True), True)
    start = _as_hour(raw.get("start", raw.get("start_hour")), fallback.start_hour)
    end = _as_hour(raw.get("end", raw.get("end_hour")), fallback.end_hour)
    if end <= start:
        start, end = fallback.start_hour, fallback.end_hour
    start = max(0, min(23, start))
    end = max(1, min(24, end))
    if end <= start:
        start, end = fallback.start_hour, fallback.end_hour
    return DayWindow(enabled=enabled, start_hour=start, end_hour=end)


def _normalize_schedule(raw: Any) -> tuple[DayWindow, ...] | None:
    if raw is None or raw == "":
        return None
    data = raw
    if isinstance(raw, str):
        import json

        try:
            data = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    days: list[DayWindow] = []
    for weekday in range(7):
        entry = data.get(str(weekday), data.get(weekday))
        days.append(_normalize_day_window(entry, weekday=weekday))
    return tuple(days)


def _legacy_schedule_from_flat(
    *,
    start_hour: int,
    end_hour: int,
    working_days: tuple[int, ...],
) -> tuple[DayWindow, ...]:
    days: list[DayWindow] = []
    for weekday in range(7):
        enabled = weekday in working_days
        if weekday >= 5 and enabled:
            days.append(DayWindow(True, DEFAULT_WEEKEND_START, DEFAULT_WEEKEND_END))
        elif enabled:
            days.append(DayWindow(True, start_hour, end_hour))
        else:
            # Keep sensible hours even when disabled so Admin shows defaults.
            days.append(
                DayWindow(
                    False,
                    DEFAULT_WEEKEND_START if weekday >= 5 else start_hour,
                    DEFAULT_WEEKEND_END if weekday >= 5 else end_hour,
                )
            )
    return tuple(days)


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
    schedule = _normalize_schedule(get_setting(db, SCHEDULE_KEY, None))
    if schedule is None:
        has_legacy = (
            get_setting(db, WORKING_DAYS_KEY, None) is not None
            or get_setting(db, START_HOUR_KEY, None) is not None
            or get_setting(db, END_HOUR_KEY, None) is not None
        )
        if not has_legacy:
            schedule = default_schedule()
        else:
            start = _as_hour(
                get_setting(db, START_HOUR_KEY, DEFAULT_WEEKDAY_START), DEFAULT_WEEKDAY_START
            )
            end = _as_hour(get_setting(db, END_HOUR_KEY, DEFAULT_WEEKDAY_END), DEFAULT_WEEKDAY_END)
            if end <= start:
                start, end = DEFAULT_WEEKDAY_START, DEFAULT_WEEKDAY_END
            working_days_raw = get_setting(db, WORKING_DAYS_KEY, None)
            if working_days_raw is None:
                weekdays_only = _as_bool(
                    get_setting(db, WEEKDAYS_ONLY_KEY, True),
                    True,
                )
                working_days = DEFAULT_WORKING_DAYS if weekdays_only else (0, 1, 2, 3, 4, 5, 6)
            else:
                working_days = _normalize_working_days(working_days_raw)
            schedule = _legacy_schedule_from_flat(
                start_hour=start, end_hour=end, working_days=working_days
            )

    return GenerationHoursConfig(
        enabled=_as_bool(get_setting(db, ENABLED_KEY, DEFAULT_ENABLED), DEFAULT_ENABLED),
        timezone_name=str(
            get_setting(db, TIMEZONE_KEY, DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
        ).strip()
        or DEFAULT_TIMEZONE,
        days=schedule,
        weekend_daily_limit=_as_positive_int(
            get_setting(db, WEEKEND_DAILY_LIMIT_KEY, DEFAULT_WEEKEND_DAILY_LIMIT),
            DEFAULT_WEEKEND_DAILY_LIMIT,
        ),
    )


def is_within_generation_hours(
    config: GenerationHoursConfig,
    *,
    now: datetime | None = None,
) -> bool:
    """True when generation stages may run.

    Window is ``start_hour <= local_hour < end_hour`` for that weekday.
    When ``enabled`` is False, always True.
    """
    if not config.enabled:
        return True

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(resolve_tz(config.timezone_name))
    day = config.days[local.weekday()]
    if not day.enabled:
        return False
    return day.start_hour <= local.hour < day.end_hour


def generation_allowed(db: Session, *, now: datetime | None = None) -> bool:
    moment = now or datetime.now(UTC)
    if is_within_generation_hours(load_generation_hours(db), now=moment):
        return True
    return manual_burst_remaining(db, now=moment) > 0


def effective_daily_limit(db: Session, *, now: datetime | None = None) -> int:
    """Weekday → queue.daily_limit; Sat/Sun → weekend cap; +manual burst headroom."""
    from db.models import Draft
    from sqlalchemy import func, select

    config = load_generation_hours(db)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(resolve_tz(config.timezone_name))
    if local.weekday() >= 5:
        base = max(1, config.weekend_daily_limit)
    else:
        base = max(
            1,
            _as_positive_int(
                get_setting(db, WEEKDAY_DAILY_LIMIT_KEY, DEFAULT_WEEKDAY_DAILY_LIMIT),
                DEFAULT_WEEKDAY_DAILY_LIMIT,
            ),
        )

    burst_left = manual_burst_remaining(db, now=moment)
    if burst_left <= 0:
        return base

    # Allow drafts_today + remaining burst so an afternoon weekend request
    # can still produce N more after the morning cap is already filled.
    local_day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_day_start.astimezone(UTC)
    drafts_today = int(
        db.scalar(select(func.count()).select_from(Draft).where(Draft.created_at >= day_start))
        or 0
    )
    return max(base, drafts_today + burst_left)


@dataclass(frozen=True, slots=True)
class ManualBurstState:
    quota: int
    created: int
    expires_at: datetime
    requested_at: datetime | None
    requested_by: str | None

    @property
    def remaining(self) -> int:
        return max(0, self.quota - self.created)

    @property
    def active(self) -> bool:
        return self.remaining > 0


def _parse_burst(raw: Any, *, now: datetime) -> ManualBurstState | None:
    if not isinstance(raw, dict):
        return None
    try:
        quota = max(1, int(raw.get("quota", 0)))
        created = max(0, int(raw.get("created", 0)))
        expires_at = datetime.fromisoformat(str(raw["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None
    if created >= quota:
        return None
    requested_at = None
    if raw.get("requested_at"):
        try:
            requested_at = datetime.fromisoformat(str(raw["requested_at"]))
            if requested_at.tzinfo is None:
                requested_at = requested_at.replace(tzinfo=UTC)
        except ValueError:
            requested_at = None
    return ManualBurstState(
        quota=quota,
        created=created,
        expires_at=expires_at,
        requested_at=requested_at,
        requested_by=str(raw["requested_by"]) if raw.get("requested_by") else None,
    )


def load_manual_burst(db: Session, *, now: datetime | None = None) -> ManualBurstState | None:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    state = _parse_burst(get_setting(db, MANUAL_BURST_KEY, None), now=moment)
    if state is None and get_setting(db, MANUAL_BURST_KEY, None) not in (None, "", {}):
        # Expired / completed — clear stale row.
        set_setting(db, MANUAL_BURST_KEY, None, description=_DESCRIPTIONS[MANUAL_BURST_KEY])
    return state


def manual_burst_remaining(db: Session, *, now: datetime | None = None) -> int:
    state = load_manual_burst(db, now=now)
    return state.remaining if state else 0


def request_manual_burst(
    db: Session,
    *,
    quota: int = DEFAULT_MANUAL_BURST_QUOTA,
    ttl_hours: int = DEFAULT_MANUAL_BURST_TTL_HOURS,
    requested_by: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ManualBurstState:
    """Start (or replace) an admin-requested generation burst."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    quota = max(1, min(200, int(quota)))
    ttl_hours = max(1, min(12, int(ttl_hours)))
    state = ManualBurstState(
        quota=quota,
        created=0,
        expires_at=moment + timedelta(hours=ttl_hours),
        requested_at=moment,
        requested_by=str(requested_by) if requested_by else None,
    )
    set_setting(
        db,
        MANUAL_BURST_KEY,
        {
            "quota": state.quota,
            "created": 0,
            "expires_at": state.expires_at.isoformat(),
            "requested_at": state.requested_at.isoformat(),
            "requested_by": state.requested_by,
        },
        description=_DESCRIPTIONS[MANUAL_BURST_KEY],
        updated_by=requested_by,
    )
    return state


def cancel_manual_burst(db: Session, *, updated_by: uuid.UUID | None = None) -> None:
    set_setting(
        db,
        MANUAL_BURST_KEY,
        None,
        description=_DESCRIPTIONS[MANUAL_BURST_KEY],
        updated_by=updated_by,
    )


def record_manual_burst_draft(
    db: Session, *, now: datetime | None = None
) -> ManualBurstState | None:
    """Increment created count after a successful dispatch during a burst."""
    moment = now or datetime.now(UTC)
    state = load_manual_burst(db, now=moment)
    if state is None:
        return None
    created = state.created + 1
    if created >= state.quota:
        cancel_manual_burst(db)
        return ManualBurstState(
            quota=state.quota,
            created=created,
            expires_at=state.expires_at,
            requested_at=state.requested_at,
            requested_by=state.requested_by,
        )
    set_setting(
        db,
        MANUAL_BURST_KEY,
        {
            "quota": state.quota,
            "created": created,
            "expires_at": state.expires_at.isoformat(),
            "requested_at": state.requested_at.isoformat() if state.requested_at else None,
            "requested_by": state.requested_by,
        },
        description=_DESCRIPTIONS[MANUAL_BURST_KEY],
    )
    return ManualBurstState(
        quota=state.quota,
        created=created,
        expires_at=state.expires_at,
        requested_at=state.requested_at,
        requested_by=state.requested_by,
    )


def manual_burst_as_dict(db: Session, *, now: datetime | None = None) -> dict[str, Any] | None:
    state = load_manual_burst(db, now=now)
    if state is None:
        return None
    return {
        "quota": state.quota,
        "created": state.created,
        "remaining": state.remaining,
        "expires_at": state.expires_at.isoformat(),
        "requested_at": state.requested_at.isoformat() if state.requested_at else None,
        "requested_by": state.requested_by,
        "active": state.active,
    }


def save_generation_hours(
    db: Session,
    *,
    enabled: bool,
    timezone_name: str,
    days: list[DayWindow] | tuple[DayWindow, ...] | None = None,
    # Legacy kwargs still accepted by older callers/tests.
    start_hour: int | None = None,
    end_hour: int | None = None,
    working_days: tuple[int, ...] | list[int] | None = None,
    weekend_daily_limit: int | None = None,
    updated_by: uuid.UUID | None = None,
) -> GenerationHoursConfig:
    tz_name = (timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    resolve_tz(tz_name)

    if days is not None:
        normalized_days = tuple(
            _normalize_day_window(
                {
                    "enabled": d.enabled,
                    "start": d.start_hour,
                    "end": d.end_hour,
                },
                weekday=i,
            )
            for i, d in enumerate(list(days)[:7])
        )
        if len(normalized_days) < 7:
            normalized_days = normalized_days + tuple(
                default_day_window(i) for i in range(len(normalized_days), 7)
            )
    else:
        flat_start = (
            DEFAULT_WEEKDAY_START if start_hour is None else max(0, min(23, int(start_hour)))
        )
        flat_end = DEFAULT_WEEKDAY_END if end_hour is None else max(1, min(24, int(end_hour)))
        if flat_end <= flat_start:
            raise ValueError("end_hour must be greater than start_hour")
        normalized_days = _legacy_schedule_from_flat(
            start_hour=flat_start,
            end_hour=flat_end,
            working_days=_normalize_working_days(
                working_days if working_days is not None else DEFAULT_WORKING_DAYS
            ),
        )

    weekend_limit = (
        DEFAULT_WEEKEND_DAILY_LIMIT
        if weekend_daily_limit is None
        else max(1, int(weekend_daily_limit))
    )

    schedule_payload = {
        str(i): {"enabled": day.enabled, "start": day.start_hour, "end": day.end_hour}
        for i, day in enumerate(normalized_days)
    }
    working = [i for i, day in enumerate(normalized_days) if day.enabled]

    values: dict[str, Any] = {
        ENABLED_KEY: bool(enabled),
        TIMEZONE_KEY: tz_name,
        SCHEDULE_KEY: schedule_payload,
        WORKING_DAYS_KEY: working,
        WEEKDAYS_ONLY_KEY: working == list(DEFAULT_WORKING_DAYS),
        WEEKEND_DAILY_LIMIT_KEY: weekend_limit,
        # Keep flat keys in sync with weekday defaults for older readers.
        START_HOUR_KEY: normalized_days[0].start_hour,
        END_HOUR_KEY: normalized_days[0].end_hour,
    }
    for key, value in values.items():
        set_setting(db, key, value, description=_DESCRIPTIONS.get(key), updated_by=updated_by)

    return GenerationHoursConfig(
        enabled=bool(enabled),
        timezone_name=tz_name,
        days=normalized_days,
        weekend_daily_limit=weekend_limit,
    )


def generation_hours_as_dict(
    config: GenerationHoursConfig, *, db: Session | None = None
) -> dict[str, Any]:
    payload = {
        "enabled": config.enabled,
        "timezone": config.timezone_name,
        "start_hour": config.start_hour,
        "end_hour": config.end_hour,
        "working_days": list(config.working_days),
        "weekend_daily_limit": config.weekend_daily_limit,
        "days": [
            {
                "weekday": i,
                "label": DAY_LABELS_RU[i],
                "enabled": day.enabled,
                "start_hour": day.start_hour,
                "end_hour": day.end_hour,
            }
            for i, day in enumerate(config.days)
        ],
        "within_hours": is_within_generation_hours(config),
        "manual_burst": None,
    }
    if db is not None:
        payload["manual_burst"] = manual_burst_as_dict(db)
        # within_hours stays schedule-only; generation_allowed includes burst.
        payload["generation_allowed"] = generation_allowed(db)
    return payload

