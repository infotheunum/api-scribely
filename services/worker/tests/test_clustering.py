from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.app_settings import set_setting
from db.enums import SourceTier, SourceType
from db.models import NewsCluster, RawItem, Source
from worker_app.dedup.clustering import recent_clusters, run_clustering_cycle, unclustered_raw_items

# Two "close" unit vectors (cosine similarity 0.9 — above threshold) and
# one "far" one (similarity 0.0 with either) — deterministic stand-ins
# for the real model so these tests don't pay for loading it.
TOPIC_A = [1.0, 0.0]
TOPIC_A_VARIANT = [0.9, (1 - 0.9**2) ** 0.5]
TOPIC_B = [0.0, 1.0]


def _source(clean_db) -> Source:
    source = Source(
        name="Test Source",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    clean_db.add(source)
    clean_db.commit()
    clean_db.refresh(source)
    return source


def _raw_item(clean_db, source, title, embedding=None, **overrides) -> RawItem:
    defaults = dict(
        source_id=source.id,
        external_id=title,
        url=f"https://example.com/{title}",
        title=title,
        body="body",
        language="en",
        trace_id="t",
        embedding=embedding,
    )
    defaults.update(overrides)
    item = RawItem(**defaults)
    clean_db.add(item)
    clean_db.commit()
    clean_db.refresh(item)
    return item


def test_two_similar_items_join_one_cluster_then_third_starts_new(clean_db, monkeypatch):
    source = _source(clean_db)
    embeddings_by_title = {
        "en-article": TOPIC_A,
        "ru-article": TOPIC_A_VARIANT,
        "unrelated": TOPIC_B,
    }
    monkeypatch.setattr(
        "worker_app.dedup.clustering.embed_text",
        lambda text: embeddings_by_title[text.split("\n")[0]],
    )

    _raw_item(clean_db, source, "en-article")
    _raw_item(clean_db, source, "ru-article", external_id="ru-article-guid")
    _raw_item(clean_db, source, "unrelated", external_id="unrelated-guid")

    stats = run_clustering_cycle(clean_db)

    assert stats == {"attached": 1, "created": 2}
    clusters = {item.title: item.cluster_id for item in clean_db.query(RawItem).all()}
    assert clusters["en-article"] == clusters["ru-article"]
    assert clusters["unrelated"] != clusters["en-article"]


def test_similarity_threshold_honors_app_setting_override(clean_db, monkeypatch):
    embeddings_by_title = {"en-article": TOPIC_A, "ru-article": TOPIC_A_VARIANT}
    monkeypatch.setattr(
        "worker_app.dedup.clustering.embed_text",
        lambda text: embeddings_by_title[text.split("\n")[0]],
    )
    # TOPIC_A_VARIANT scores 0.9 against TOPIC_A — passes the 0.6 default
    # but not a much stricter 0.99 threshold set via AppSetting.
    set_setting(clean_db, "dedup.similarity_threshold", 0.99)
    clean_db.commit()

    _raw_item(clean_db, source := _source(clean_db), "en-article")
    _raw_item(clean_db, source, "ru-article", external_id="ru-article-guid")

    stats = run_clustering_cycle(clean_db)

    assert stats == {"attached": 0, "created": 2}


def test_already_clustered_items_are_left_alone(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    clean_db.refresh(cluster)

    item = _raw_item(clean_db, source, "already-done", embedding=TOPIC_A, cluster_id=cluster.id)

    assert unclustered_raw_items(clean_db) == []
    assert item.cluster_id == cluster.id


def test_recent_clusters_excludes_old_ones(clean_db):
    fresh = NewsCluster(embedding=TOPIC_A, trace_id="t")
    stale = NewsCluster(embedding=TOPIC_A, trace_id="t")
    clean_db.add_all([fresh, stale])
    clean_db.commit()
    clean_db.execute(
        NewsCluster.__table__.update()
        .where(NewsCluster.id == stale.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=10))
    )
    clean_db.commit()

    ids = {c.id for c in recent_clusters(clean_db)}
    assert fresh.id in ids
    assert stale.id not in ids
