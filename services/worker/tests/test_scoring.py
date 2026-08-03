from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.enums import SourceTier, SourceType
from db.models import NewsCluster, RawItem, Source
from worker_app.filter.scoring import (
    FRESHNESS_WEIGHT,
    SOURCE_COUNT_WEIGHT,
    TIER_WEIGHT,
    compute_priority_score,
)


def _source(clean_db, tier, name="s") -> Source:
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        type=SourceType.RSS,
        tier=tier,
        language="en",
    )
    clean_db.add(source)
    clean_db.commit()
    clean_db.refresh(source)
    return source


def _cluster_with_items(clean_db, sources, *, created_at) -> NewsCluster:
    cluster = NewsCluster(trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    for i, source in enumerate(sources):
        clean_db.add(
            RawItem(
                source_id=source.id,
                external_id=f"item-{cluster.id}-{i}",
                url=f"https://example.com/{cluster.id}-{i}",
                title="t",
                language="en",
                trace_id="t",
                cluster_id=cluster.id,
            )
        )
    clean_db.commit()
    clean_db.execute(
        NewsCluster.__table__.update()
        .where(NewsCluster.id == cluster.id)
        .values(created_at=created_at)
    )
    clean_db.commit()
    clean_db.refresh(cluster)
    return cluster


def test_more_sources_scores_higher(clean_db):
    now = datetime.now(UTC)
    tier1 = _source(clean_db, SourceTier.TIER_1, "a")
    tier1b = _source(clean_db, SourceTier.TIER_1, "b")

    single = _cluster_with_items(clean_db, [tier1], created_at=now)
    multi = _cluster_with_items(clean_db, [tier1, tier1b], created_at=now)

    assert compute_priority_score(multi, now=now) > compute_priority_score(single, now=now)
    assert (
        compute_priority_score(multi, now=now) - compute_priority_score(single, now=now)
        == SOURCE_COUNT_WEIGHT
    )


def test_lower_tier_number_scores_higher(clean_db):
    now = datetime.now(UTC)
    tier1 = _source(clean_db, SourceTier.TIER_1, "a")
    tier6 = _source(clean_db, SourceTier.TIER_6, "b")

    from_tier1 = _cluster_with_items(clean_db, [tier1], created_at=now)
    from_tier6 = _cluster_with_items(clean_db, [tier6], created_at=now)

    assert compute_priority_score(from_tier1, now=now) > compute_priority_score(from_tier6, now=now)


def test_older_clusters_score_lower(clean_db):
    now = datetime.now(UTC)
    source = _source(clean_db, SourceTier.TIER_1, "a")

    fresh = _cluster_with_items(clean_db, [source], created_at=now)
    old = _cluster_with_items(clean_db, [source], created_at=now - timedelta(hours=48))

    assert compute_priority_score(fresh, now=now) > compute_priority_score(old, now=now)


def test_score_beyond_freshness_window_has_no_freshness_component(clean_db):
    now = datetime.now(UTC)
    source = _source(clean_db, SourceTier.TIER_1, "a")
    ancient = _cluster_with_items(clean_db, [source], created_at=now - timedelta(hours=200))

    score = compute_priority_score(ancient, now=now)
    expected_floor = SOURCE_COUNT_WEIGHT * 1 + TIER_WEIGHT * (7 - 1)
    assert abs(score - expected_floor) < 1e-9
    assert FRESHNESS_WEIGHT > 0  # sanity: the weight itself isn't zero
