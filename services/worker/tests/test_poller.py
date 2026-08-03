from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.enums import SourceTier, SourceType
from db.models import RawItem, Source
from worker_app.ingestion.circuit_breaker import CONSECUTIVE_FAILURE_THRESHOLD
from worker_app.ingestion.poller import due_sources, poll_source
from worker_app.ingestion.rss_connector import FeedFetchError, ParsedEntry


def _make_source(clean_db, **overrides) -> Source:
    defaults = dict(
        name="Test Source",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
        poll_interval_seconds=900,
    )
    defaults.update(overrides)
    source = Source(**defaults)
    clean_db.add(source)
    clean_db.commit()
    clean_db.refresh(source)
    return source


def test_poll_source_creates_raw_items_and_is_idempotent(clean_db, monkeypatch):
    source = _make_source(clean_db)
    entries = [
        ParsedEntry(
            external_id="guid-1",
            url="https://example.com/1",
            title="Article 1",
            summary="A" * 700,
            published_at=None,
        ),
        ParsedEntry(
            external_id="guid-2",
            url="https://example.com/2",
            title="Article 2",
            summary="short",
            published_at=None,
        ),
    ]
    monkeypatch.setattr("worker_app.ingestion.poller.fetch_feed_entries", lambda *a, **kw: entries)
    monkeypatch.setattr(
        "worker_app.ingestion.poller.fetch_full_text", lambda *a, **kw: "fetched full text"
    )

    created = poll_source(clean_db, source)
    assert created == 2
    assert clean_db.query(RawItem).count() == 2

    # second poll of the same entries must not duplicate (idempotency)
    created_again = poll_source(clean_db, source)
    assert created_again == 0
    assert clean_db.query(RawItem).count() == 2


def test_poll_source_fetches_full_text_for_summary_only_tier1(clean_db, monkeypatch):
    source = _make_source(clean_db, tier=SourceTier.TIER_1)
    entries = [
        ParsedEntry(
            external_id="guid-short",
            url="https://example.com/short",
            title="Short",
            summary="short teaser",
            published_at=None,
        )
    ]
    monkeypatch.setattr("worker_app.ingestion.poller.fetch_feed_entries", lambda *a, **kw: entries)
    monkeypatch.setattr(
        "worker_app.ingestion.poller.fetch_full_text", lambda *a, **kw: "the real full article"
    )

    poll_source(clean_db, source)

    raw_item = clean_db.query(RawItem).one()
    assert raw_item.is_full_text is True
    assert raw_item.body == "the real full article"


def test_poll_source_records_failure_and_trips_breaker(clean_db, monkeypatch):
    source = _make_source(clean_db)

    def _raise(*args, **kwargs):
        raise FeedFetchError("boom")

    monkeypatch.setattr("worker_app.ingestion.poller.fetch_feed_entries", _raise)

    for _ in range(CONSECUTIVE_FAILURE_THRESHOLD):
        created = poll_source(clean_db, source)
        assert created == 0

    clean_db.refresh(source)
    assert source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD
    assert source.paused_until is not None
    assert due_sources(clean_db) == []


def test_due_sources_excludes_not_yet_due(clean_db):
    _make_source(clean_db, name="Just polled", poll_interval_seconds=3600)
    clean_db.query(Source).filter_by(name="Just polled").update(
        {"last_polled_at": datetime.now(UTC)}
    )
    _make_source(
        clean_db,
        name="Overdue",
        url="https://example.com/feed2",
        poll_interval_seconds=60,
    )
    clean_db.query(Source).filter_by(name="Overdue").update(
        {"last_polled_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    clean_db.commit()

    due = due_sources(clean_db)
    assert [s.name for s in due] == ["Overdue"]
