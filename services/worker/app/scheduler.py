from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from common.generation_hours import generation_allowed
from db.app_settings import get_setting
from worker_app.db import new_session
from worker_app.settings import WorkerSettings

logger = logging.getLogger(__name__)

# A tick just checks which sources are due (per their own
# poll_interval_seconds, ТЗ §4.1) and polls those — the tick itself can
# run often and cheaply.
POLL_TICK_SECONDS = 60

# Independent on/off switches per stage (ТЗ §4.21, Admin Settings) — an
# operator can pause e.g. just dispatch (a prompt is burning free-tier
# quota) without touching ingestion, or vice versa, without a redeploy.
# Checked fresh every tick, same as every other AppSetting.
_STAGE_SETTING_KEYS = {
    "poll": "pipeline.poll_enabled",
    "cluster": "pipeline.cluster_enabled",
    "filter": "pipeline.filter_enabled",
    "dispatch": "pipeline.dispatch_enabled",
    "compliance": "pipeline.compliance_enabled",
    "archival": "pipeline.archival_enabled",
}

# Stages that produce / advance article generation. Outside working hours
# these skip; archival and categories sync keep running.
_GENERATION_STAGES = frozenset({"poll", "cluster", "filter", "dispatch", "compliance"})


def _stage_enabled(session, stage: str) -> bool:
    if not bool(get_setting(session, _STAGE_SETTING_KEYS[stage], True)):
        return False
    if stage in _GENERATION_STAGES and not generation_allowed(session):
        return False
    return True


def _run_cluster_tick() -> None:
    """Cross-language clustering (ТЗ §4.2) — separate job so slow CPU
    embedding does not block poll/filter/dispatch."""
    from worker_app.dedup.clustering import run_clustering_cycle

    session = new_session()
    try:
        if _stage_enabled(session, "cluster"):
            stats = run_clustering_cycle(session)
            if stats["attached"] or stats["created"]:
                logger.info("clustering tick: %s", stats)
    except Exception:
        logger.exception("clustering tick failed unexpectedly")
    finally:
        session.close()


def _run_poll_tick() -> None:
    from worker_app.compliance.pipeline import run_compliance_cycle
    from worker_app.dispatch.pipeline import run_dispatch_cycle
    from worker_app.filter.pipeline import run_filter_cycle
    from worker_app.ingestion.poller import poll_due_sources
    from worker_app.lifecycle.archival import run_archival_cycle

    session = new_session()
    try:
        if _stage_enabled(session, "poll"):
            results = poll_due_sources(session)
            if results:
                logger.info("poll tick: %s", results)
    except Exception:
        logger.exception("poll tick failed unexpectedly")
    finally:
        session.close()

    # Topic filter + priority scoring (ТЗ §4.3) — clustering runs in a
    # parallel scheduler job; filter picks up clusters as they appear.
    session = new_session()
    try:
        if _stage_enabled(session, "filter"):
            stats = run_filter_cycle(session)
            if stats["classified"]:
                logger.info("filter tick: %s", stats)
    except Exception:
        logger.exception("filter tick failed unexpectedly")
    finally:
        session.close()

    # Enrich+Rewrite dispatch (ТЗ §4.4-§4.13, Фаза 4) — depends on this
    # cycle's own filter results, and it's the slowest stage by far
    # (real OpenRouter free-tier latency).
    session = new_session()
    try:
        if _stage_enabled(session, "dispatch"):
            stats = run_dispatch_cycle(session)
            if stats["dispatched"] or stats["failed"]:
                logger.info("dispatch tick: %s", stats)
    except Exception:
        logger.exception("dispatch tick failed unexpectedly")
    finally:
        session.close()

    # Policy/Compliance Checker (ТЗ §4.6, §4.20, Фаза 5) — gates every
    # Draft dispatch left in DRAFTING before it can reach the review
    # queue. Last in the tick since it depends on this cycle's own
    # dispatch output.
    session = new_session()
    try:
        if _stage_enabled(session, "compliance"):
            stats = run_compliance_cycle(session)
            if stats["reviewed"]:
                logger.info("compliance tick: %s", stats)
    except Exception:
        logger.exception("compliance tick failed unexpectedly")
    finally:
        session.close()

    # TTL-архивация (ТЗ §4.20, §6.5, Фаза 6) — a draft that sat in
    # READY_FOR_REVIEW past the TTL without a human decision archives
    # itself; cheap query, fine to run every tick like everything else.
    # Not gated by generation hours — cleanup must keep working overnight.
    session = new_session()
    try:
        if _stage_enabled(session, "archival"):
            stats = run_archival_cycle(session)
            if stats["archived"]:
                logger.info("archival tick: %s", stats)
    except Exception:
        logger.exception("archival tick failed unexpectedly")
    finally:
        session.close()


def _run_categories_sync_tick() -> None:
    from worker_app.sync.theunum_categories import run_theunum_categories_sync_if_due

    session = new_session()
    try:
        stats = run_theunum_categories_sync_if_due(session, WorkerSettings())
        if stats:
            logger.info("categories sync tick: %s", stats)
    except Exception:
        logger.exception("categories sync tick failed unexpectedly")
    finally:
        session.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_poll_tick, "interval", seconds=POLL_TICK_SECONDS, id="poll_pipeline")
    scheduler.add_job(
        _run_cluster_tick,
        "interval",
        seconds=POLL_TICK_SECONDS,
        id="cluster_dedup",
        max_instances=1,
    )
    scheduler.add_job(
        _run_categories_sync_tick,
        "interval",
        hours=1,
        id="theunum_categories_sync",
    )
    return scheduler
