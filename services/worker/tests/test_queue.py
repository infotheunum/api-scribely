from __future__ import annotations

from db.enums import SourceTier, SourceType, TopicStatus
from db.models import NewsCluster, RawItem, Source
from worker_app.filter.queue import select_top_clusters


def _source(clean_db, name) -> Source:
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    clean_db.add(source)
    clean_db.commit()
    clean_db.refresh(source)
    return source


def _cluster(clean_db, source, *, score, topic_status=TopicStatus.IN_TOPIC) -> NewsCluster:
    cluster = NewsCluster(trace_id="t", priority_score=score, topic_status=topic_status)
    clean_db.add(cluster)
    clean_db.commit()
    clean_db.add(
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
    clean_db.commit()
    clean_db.refresh(cluster)
    return cluster


def test_out_of_topic_clusters_are_excluded(clean_db):
    source = _source(clean_db, "s")
    in_topic = _cluster(clean_db, source, score=10, topic_status=TopicStatus.IN_TOPIC)
    _cluster(clean_db, source, score=20, topic_status=TopicStatus.OUT_OF_TOPIC)
    _cluster(clean_db, source, score=30, topic_status=TopicStatus.PENDING)

    selected = select_top_clusters(clean_db, limit=10, fairness_cap_ratio=1.0)

    assert [c.id for c in selected] == [in_topic.id]


def test_selection_is_priority_ordered(clean_db):
    source = _source(clean_db, "s")
    low = _cluster(clean_db, source, score=1)
    high = _cluster(clean_db, source, score=99)
    mid = _cluster(clean_db, source, score=50)

    selected = select_top_clusters(clean_db, limit=10, fairness_cap_ratio=1.0)

    assert [c.id for c in selected] == [high.id, mid.id, low.id]


def test_fairness_cap_limits_single_source_share(clean_db):
    noisy = _source(clean_db, "noisy")
    quiet = _source(clean_db, "quiet")
    # 8 clusters from the noisy source, all outscoring the one quiet
    # cluster — without a fairness cap the quiet source would never
    # make it into a small top-N.
    for i in range(8):
        _cluster(clean_db, noisy, score=100 - i)
    quiet_cluster = _cluster(clean_db, quiet, score=1)

    selected = select_top_clusters(clean_db, limit=5, fairness_cap_ratio=0.4)

    noisy_selected = [c for c in selected if c.raw_items[0].source_id == noisy.id]
    assert len(noisy_selected) <= 2  # 0.4 * 5 = 2
    assert quiet_cluster.id in [c.id for c in selected]


def test_limit_caps_total_selected(clean_db):
    source = _source(clean_db, "s")
    for i in range(5):
        _cluster(clean_db, source, score=i)

    selected = select_top_clusters(clean_db, limit=2, fairness_cap_ratio=1.0)

    assert len(selected) == 2
