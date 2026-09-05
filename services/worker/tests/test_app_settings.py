from __future__ import annotations

from db.app_settings import get_setting, set_setting
from worker_app.scheduler import _stage_enabled


def test_get_setting_returns_default_when_unseeded(clean_db):
    assert get_setting(clean_db, "does.not.exist", "fallback") == "fallback"


def test_set_then_get_setting_roundtrips(clean_db):
    set_setting(clean_db, "dispatch.batch_size", 7)
    clean_db.commit()

    assert get_setting(clean_db, "dispatch.batch_size", 1) == 7


def test_set_setting_updates_existing_row(clean_db):
    set_setting(clean_db, "queue.daily_limit", 50)
    clean_db.commit()
    set_setting(clean_db, "queue.daily_limit", 75)
    clean_db.commit()

    assert get_setting(clean_db, "queue.daily_limit", 0) == 75


def test_stage_enabled_defaults_true_when_unseeded(clean_db, monkeypatch):
    monkeypatch.setattr(
        "worker_app.scheduler.generation_allowed",
        lambda _session: True,
    )
    assert _stage_enabled(clean_db, "dispatch") is True


def test_stage_enabled_respects_kill_switch(clean_db, monkeypatch):
    monkeypatch.setattr(
        "worker_app.scheduler.generation_allowed",
        lambda _session: True,
    )
    set_setting(clean_db, "pipeline.dispatch_enabled", False)
    clean_db.commit()

    assert _stage_enabled(clean_db, "dispatch") is False
    assert _stage_enabled(clean_db, "poll") is True
