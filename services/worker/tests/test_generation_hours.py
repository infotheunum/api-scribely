from __future__ import annotations

from datetime import UTC, datetime

from common.generation_hours import (
    ENABLED_KEY,
    DayWindow,
    GenerationHoursConfig,
    default_schedule,
    effective_daily_limit,
    is_within_generation_hours,
    load_generation_hours,
    save_generation_hours,
)
from db.app_settings import set_setting
from worker_app.scheduler import _stage_enabled


def _cfg(**overrides) -> GenerationHoursConfig:
    days = overrides.pop("days", None)
    if days is None:
        days = default_schedule()
        # Legacy tests expect weekends off unless working_days overrides.
        if "working_days" in overrides:
            working = set(overrides.pop("working_days"))
            days = tuple(
                DayWindow(
                    enabled=i in working,
                    start_hour=d.start_hour,
                    end_hour=d.end_hour,
                )
                for i, d in enumerate(days)
            )
        else:
            days = tuple(
                DayWindow(enabled=i < 5, start_hour=d.start_hour, end_hour=d.end_hour)
                for i, d in enumerate(days)
            )
    base = dict(
        enabled=True,
        timezone_name="Europe/Minsk",
        days=days,
        weekend_daily_limit=25,
    )
    base.update(overrides)
    return GenerationHoursConfig(**base)


def test_weekday_morning_inside_window():
    # 2026-09-07 is Monday; 06:30 Minsk = 03:30 UTC
    now = datetime(2026, 9, 7, 3, 30, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is True


def test_weekday_evening_outside_window():
    # Monday 18:00 Minsk = 15:00 UTC — end exclusive
    now = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_weekday_before_start_outside():
    # Monday 05:59 Minsk = 02:59 UTC
    now = datetime(2026, 9, 7, 2, 59, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_saturday_outside_when_weekend_disabled():
    # 2026-09-05 is Saturday; 12:00 Minsk = 09:00 UTC
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_sunday_outside_when_weekend_disabled():
    now = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_disabled_gate_always_allows():
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)  # Saturday
    assert is_within_generation_hours(_cfg(enabled=False), now=now) is True


def test_saturday_inside_default_weekend_window():
    # Saturday 07:00 Minsk = 04:00 UTC — default weekend 06–09
    now = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)
    days = default_schedule()
    assert is_within_generation_hours(_cfg(days=days), now=now) is True


def test_saturday_outside_after_nine():
    # Saturday 09:00 Minsk = 06:00 UTC — end exclusive
    now = datetime(2026, 9, 5, 6, 0, tzinfo=UTC)
    days = default_schedule()
    assert is_within_generation_hours(_cfg(days=days), now=now) is False


def test_load_defaults_when_unseeded(clean_db):
    cfg = load_generation_hours(clean_db)
    assert cfg.enabled is True
    assert cfg.timezone_name == "Europe/Minsk"
    assert cfg.start_hour == 6
    assert cfg.end_hour == 18
    assert cfg.working_days == (0, 1, 2, 3, 4, 5, 6)
    assert cfg.days[0].start_hour == 6 and cfg.days[0].end_hour == 18
    assert cfg.days[5].enabled is True
    assert cfg.days[5].start_hour == 6
    assert cfg.days[5].end_hour == 9
    assert cfg.weekend_daily_limit == 25


def test_save_and_load_per_day_roundtrip(clean_db):
    days = list(default_schedule())
    days[5] = DayWindow(True, 9, 14)
    days[6] = DayWindow(False, 9, 12)
    save_generation_hours(
        clean_db,
        enabled=True,
        timezone_name="Europe/Moscow",
        days=days,
        weekend_daily_limit=40,
    )
    clean_db.commit()
    cfg = load_generation_hours(clean_db)
    assert cfg.timezone_name == "Europe/Moscow"
    assert cfg.days[5].enabled is True
    assert cfg.days[5].start_hour == 9
    assert cfg.days[5].end_hour == 14
    assert cfg.days[6].enabled is False
    assert cfg.weekend_daily_limit == 40


def test_legacy_save_still_works(clean_db):
    save_generation_hours(
        clean_db,
        enabled=True,
        timezone_name="Europe/Moscow",
        start_hour=7,
        end_hour=19,
        working_days=(0, 1, 2, 3, 4),
    )
    clean_db.commit()
    cfg = load_generation_hours(clean_db)
    assert cfg.timezone_name == "Europe/Moscow"
    assert cfg.days[0].start_hour == 7
    assert cfg.days[0].end_hour == 19
    assert cfg.days[5].enabled is False


def test_effective_daily_limit_weekday_vs_weekend(clean_db):
    set_setting(clean_db, "queue.daily_limit", 300)
    set_setting(clean_db, "queue.weekend_daily_limit", 25)
    clean_db.commit()
    monday = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    saturday = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    assert effective_daily_limit(clean_db, now=monday) == 300
    assert effective_daily_limit(clean_db, now=saturday) == 25


def test_manual_burst_allows_generation_outside_hours(clean_db):
    from common.generation_hours import (
        generation_allowed,
        manual_burst_remaining,
        record_manual_burst_draft,
        request_manual_burst,
    )

    # Saturday 15:00 Minsk = 12:00 UTC — outside 06–09
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    assert generation_allowed(clean_db, now=now) is False
    request_manual_burst(clean_db, quota=2, ttl_hours=1, now=now)
    clean_db.commit()
    assert generation_allowed(clean_db, now=now) is True
    assert manual_burst_remaining(clean_db, now=now) == 2
    record_manual_burst_draft(clean_db, now=now)
    clean_db.commit()
    assert manual_burst_remaining(clean_db, now=now) == 1
    record_manual_burst_draft(clean_db, now=now)
    clean_db.commit()
    assert manual_burst_remaining(clean_db, now=now) == 0
    assert generation_allowed(clean_db, now=now) is False


def test_stage_enabled_respects_generation_hours(clean_db, monkeypatch):
    set_setting(clean_db, ENABLED_KEY, True)
    clean_db.commit()

    monkeypatch.setattr(
        "worker_app.scheduler.generation_allowed",
        lambda _session: False,
    )
    assert _stage_enabled(clean_db, "dispatch") is False
    assert _stage_enabled(clean_db, "poll") is False
    assert _stage_enabled(clean_db, "archival") is True


def test_stage_enabled_inside_hours(clean_db, monkeypatch):
    monkeypatch.setattr(
        "worker_app.scheduler.generation_allowed",
        lambda _session: True,
    )
    assert _stage_enabled(clean_db, "dispatch") is True
