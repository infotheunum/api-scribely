from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from worker_app.db import new_session
from worker_app.dedup.clustering import run_clustering_cycle
from worker_app.filter.pipeline import run_filter_cycle
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

    # Cross-language clustering (ТЗ §4.2, План §4) — runs right after
    # ingestion in the same tick so freshly-polled items don't sit
    # unclustered until the next cycle.
    session = new_session()
    try:
        stats = run_clustering_cycle(session)
        if stats["attached"] or stats["created"]:
            logger.info("clustering tick: %s", stats)
    except Exception:
        logger.exception("clustering tick failed unexpectedly")
    finally:
        session.close()

    # Topic filter + priority scoring (ТЗ §4.3) — runs right after
    # clustering, same tick, so a freshly-formed cluster gets a
    # in-topic/out-of-topic flag and a score before the next poll cycle.
    session = new_session()
    try:
        stats = run_filter_cycle(session)
        if stats["classified"]:
            logger.info("filter tick: %s", stats)
    except Exception:
        logger.exception("filter tick failed unexpectedly")
    finally:
        session.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_poll_tick, "interval", seconds=POLL_TICK_SECONDS, id="poll_sources")
    return scheduler
