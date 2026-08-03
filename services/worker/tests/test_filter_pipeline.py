from __future__ import annotations

from db.enums import SourceTier, SourceType, TopicStatus
from db.models import NewsCluster, RawItem, Source
from worker_app.filter.pipeline import run_filter_cycle


def _source(clean_db) -> Source:
    source = Source(
        name="s",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    clean_db.add(source)
    clean_db.commit()
    clean_db.refresh(source)
    return source


def _pending_cluster(clean_db, source, title) -> NewsCluster:
    cluster = NewsCluster(trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    clean_db.add(
        RawItem(
            source_id=source.id,
            external_id=f"item-{cluster.id}",
            url=f"https://example.com/{cluster.id}",
            title=title,
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    clean_db.commit()
    clean_db.refresh(cluster)
    return cluster


def test_run_filter_cycle_classifies_and_scores(clean_db):
    source = _source(clean_db)
    crypto = _pending_cluster(clean_db, source, "Bitcoin ETF sees record inflows")
    unrelated = _pending_cluster(clean_db, source, "New humanoid robot unveiled at expo")

    stats = run_filter_cycle(clean_db)

    assert stats["classified"] == 2
    clean_db.refresh(crypto)
    clean_db.refresh(unrelated)

    assert crypto.topic_status == TopicStatus.IN_TOPIC
    assert crypto.topic == "Криптовалюты и цифровые активы"
    assert crypto.priority_score > 0

    assert unrelated.topic_status == TopicStatus.OUT_OF_TOPIC
    assert unrelated.topic is None


def test_run_filter_cycle_is_idempotent_on_already_classified(clean_db):
    source = _source(clean_db)
    _pending_cluster(clean_db, source, "Bitcoin surges past $120,000")

    first = run_filter_cycle(clean_db)
    second = run_filter_cycle(clean_db)

    assert first["classified"] == 1
    assert second["classified"] == 0  # already classified, not PENDING anymore
