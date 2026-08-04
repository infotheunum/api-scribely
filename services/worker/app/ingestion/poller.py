from __future__ import annotations

import logging
from datetime import UTC, datetime

from common.fulltext import fetch_full_text
from common.tracing import new_trace_id
from db.enums import SourceTier, SourceType
from db.models import RawItem, Source
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.ingestion.circuit_breaker import is_paused, record_failure, record_success
from worker_app.ingestion.rss_connector import FeedFetchError, fetch_feed_entries

logger = logging.getLogger(__name__)


def due_sources(db: Session, *, now: datetime | None = None) -> list[Source]:
    """Active, not circuit-broken, RSS sources whose poll_interval has
    elapsed. API connectors (Уровень 2) are out of Phase 1 scope (План §3)."""
    now = now or datetime.now(UTC)
    candidates = db.scalars(
        select(Source).where(Source.is_active.is_(True), Source.type == SourceType.RSS)
    ).all()
    due = []
    for source in candidates:
        if is_paused(source):
            continue
        if source.last_polled_at is None:
            due.append(source)
            continue
        elapsed = (now - source.last_polled_at).total_seconds()
        if elapsed >= source.poll_interval_seconds:
            due.append(source)
    return due


def _raw_item_exists(db: Session, source_id, external_id: str) -> bool:
    return (
        db.scalar(
            select(RawItem.id).where(
                RawItem.source_id == source_id, RawItem.external_id == external_id
            )
        )
        is not None
    )


def poll_source(db: Session, source: Source) -> int:
    """Polls one source and persists new RawItems. Never raises — a
    single source's failure must not stop the rest of the cycle (ТЗ §5);
    failures are recorded against the circuit breaker instead."""
    trace_id = new_trace_id()
    try:
        entries = fetch_feed_entries(source.url, user_agent=source.config.get("user_agent"))
    except FeedFetchError:
        logger.warning("poll failed for source %s (%s)", source.name, source.id, exc_info=True)
        record_failure(db, source)
        db.commit()
        return 0

    created = 0
    for entry in entries:
        if _raw_item_exists(db, source.id, entry.external_id):
            continue

        body = entry.summary
        is_full_text = False
        if source.tier == SourceTier.TIER_1 and entry.looks_summary_only:
            full_text = fetch_full_text(entry.url, user_agent=source.config.get("user_agent"))
            if full_text:
                body = full_text
                is_full_text = True

        db.add(
            RawItem(
                source_id=source.id,
                external_id=entry.external_id,
                url=entry.url,
                title=entry.title or entry.url,
                body=body,
                is_full_text=is_full_text,
                language=source.language,
                published_at=entry.published_at,
                trace_id=trace_id,
            )
        )
        created += 1

    record_success(source)
    db.commit()
    logger.info("polled source %s (%s): %d new items", source.name, source.id, created)
    return created


def poll_due_sources(db: Session) -> dict[str, int]:
    """One scheduler tick: polls every source that's currently due.
    Returns {source_name: new_item_count} for logging/observability."""
    results: dict[str, int] = {}
    for source in due_sources(db):
        results[source.name] = poll_source(db, source)
    return results
