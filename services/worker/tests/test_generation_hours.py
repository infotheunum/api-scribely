from __future__ import annotations

from datetime import UTC, datetime

from common.generation_hours import (
    ENABLED_KEY,
    GenerationHoursConfig,
    is_within_generation_hours,
    load_generation_hours,
    save_generation_hours,
)
from db.app_settings import set_setting
from worker_app.scheduler import _stage_enabled


def _cfg(**overrides) -> GenerationHoursConfig:
    base = dict(
        enabled=True,
        timezone_name="Europe/Minsk",
        start_hour=6,
        end_hour=18,
        working_days=(0, 1, 2, 3, 4),
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


def test_saturday_outside_even_at_noon():
    # 2026-09-05 is Saturday; 12:00 Minsk = 09:00 UTC
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_sunday_outside():
    # 2026-09-06 is Sunday
    now = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
    assert is_within_generation_hours(_cfg(), now=now) is False


def test_disabled_gate_always_allows():
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)  # Saturday
    assert is_within_generation_hours(_cfg(enabled=False), now=now) is True


def test_weekend_allowed_when_enabled():
    now = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)  # Saturday noon Minsk
    assert is_within_generation_hours(_cfg(working_days=(0, 1, 2, 3, 4, 5, 6)), now=now) is True


def test_load_defaults_when_unseeded(clean_db):
    cfg = load_generation_hours(clean_db)
    assert cfg.enabled is True
    assert cfg.timezone_name == "Europe/Minsk"
    assert cfg.start_hour == 6
    assert cfg.end_hour == 18
    assert cfg.working_days == (0, 1, 2, 3, 4)


def test_save_and_load_roundtrip(clean_db):
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
    assert cfg.start_hour == 7
    assert cfg.end_hour == 19


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
