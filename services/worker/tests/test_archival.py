from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.app_settings import set_setting
from db.enums import DraftStatus, SourceTier, SourceType
from db.models import Draft, NewsCluster, RawItem, Source
from worker_app.lifecycle.archival import run_archival_cycle


def _source(db) -> Source:
    source = Source(
        name="s",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _cluster(db, source) -> NewsCluster:
    cluster = NewsCluster(trace_id="t")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id=f"item-{cluster.id}",
            url=f"https://example.com/{cluster.id}",
            title="t",
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    db.commit()
    db.refresh(cluster)
    return cluster


def _draft(db, cluster, *, created_at, status=DraftStatus.READY_FOR_REVIEW) -> Draft:
    draft = Draft(
        cluster_id=cluster.id,
        title_en="x",
        body_en="x" * 150,
        title_ru="y",
        body_ru="y" * 150,
        trace_id="t",
        status=status,
    )
    db.add(draft)
    db.commit()
    db.execute(Draft.__table__.update().where(Draft.id == draft.id).values(created_at=created_at))
    db.commit()
    db.refresh(draft)
    return draft


def test_stale_ready_for_review_gets_archived(clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    old = _draft(clean_db, cluster, created_at=datetime.now(UTC) - timedelta(hours=100))

    stats = run_archival_cycle(clean_db)

    clean_db.refresh(old)
    assert stats["archived"] == 1
    assert old.status == DraftStatus.ARCHIVED


def test_fresh_draft_is_left_alone(clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    fresh = _draft(clean_db, cluster, created_at=datetime.now(UTC) - timedelta(hours=1))

    stats = run_archival_cycle(clean_db)

    clean_db.refresh(fresh)
    assert stats["archived"] == 0
    assert fresh.status == DraftStatus.READY_FOR_REVIEW


def test_non_ready_statuses_are_never_archived(clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    needs_fix = _draft(
        clean_db,
        cluster,
        created_at=datetime.now(UTC) - timedelta(hours=100),
        status=DraftStatus.NEEDS_FIX,
    )

    stats = run_archival_cycle(clean_db)

    clean_db.refresh(needs_fix)
    assert stats["archived"] == 0
    assert needs_fix.status == DraftStatus.NEEDS_FIX


def test_ttl_honors_app_setting_override(clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster, created_at=datetime.now(UTC) - timedelta(hours=2))
    set_setting(clean_db, "queue.ttl_archive_hours", 1)
    clean_db.commit()

    stats = run_archival_cycle(clean_db)

    clean_db.refresh(draft)
    assert stats["archived"] == 1
    assert draft.status == DraftStatus.ARCHIVED
