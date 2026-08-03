from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from worker_app.db import new_session
from worker_app.ingestion.poller import poll_due_sources

logger = logging.getLogger(__name__)

# A tick just checks which sources are due (per their own
# poll_interval_seconds, ТЗ §4.1) and polls those — the tick itself can
# run often and cheaply.
POLL_TICK_SECONDS = 60


def _run_poll_tick() -> None:
    session = new_session()
    try:
        results = poll_due_sources(session)
        if results:
            logger.info("poll tick: %s", results)
    except Exception:
        logger.exception("poll tick failed unexpectedly")
    finally:
        session.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_poll_tick, "interval", seconds=POLL_TICK_SECONDS, id="poll_sources")
    return scheduler
