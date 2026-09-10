from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.app_settings import set_setting
from db.enums import SourceTier, SourceType
from db.models import NewsCluster, RawItem, Source
from sqlalchemy import inspect
from worker_app.dedup.clustering import (
    candidate_clusters,
    cluster_raw_item,
    recent_clusters,
    run_clustering_cycle,
    unclustered_raw_items,
)

# Two "close" unit vectors (cosine similarity 0.9 — above threshold) and
# one "far" one (similarity 0.0 with either) — deterministic stand-ins
# for the real model so these tests don't pay for loading it.
TOPIC_A = [1.0, 0.0]
TOPIC_A_VARIANT = [0.9, (1 - 0.9**2) ** 0.5]
TOPIC_A_SECOND_VARIANT = [0.8, (1 - 0.8**2) ** 0.5]
TOPIC_B = [0.0, 1.0]


def _mock_embed_texts_factory(embeddings_by_title: dict[str, list[float]]):
    def _mock(texts, **kwargs):
        return [embeddings_by_title[t.split("\n")[0]] for t in texts]

    return _mock


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
        "worker_app.dedup.clustering.embed_texts",
        _mock_embed_texts_factory(embeddings_by_title),
    )
    monkeypatch.setattr(
        "worker_app.dedup.clustering.confirm_duplicate_with_llm",
        lambda *_: True,
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
        "worker_app.dedup.clustering.embed_texts",
        _mock_embed_texts_factory(embeddings_by_title),
    )
    monkeypatch.setattr(
        "worker_app.dedup.clustering.confirm_duplicate_with_llm",
        lambda *_: False,
    )
    # TOPIC_A_VARIANT scores 0.9 against TOPIC_A — passes the 0.6 default
    # but not a much stricter 0.99 threshold set via AppSetting.
    set_setting(clean_db, "dedup.similarity_threshold", 0.99)
    clean_db.commit()

    _raw_item(clean_db, source := _source(clean_db), "en-article")
    _raw_item(clean_db, source, "ru-article", external_id="ru-article-guid")

    stats = run_clustering_cycle(clean_db)

    assert stats == {"attached": 0, "created": 2}


def test_cluster_per_tick_limit_caps_batch(clean_db, monkeypatch):
    source = _source(clean_db)
    embeddings_by_title = {
        "a": TOPIC_A,
        "b": TOPIC_B,
        "c": TOPIC_B,
    }
    monkeypatch.setattr(
        "worker_app.dedup.clustering.embed_texts",
        _mock_embed_texts_factory(embeddings_by_title),
    )
    set_setting(clean_db, "dedup.cluster_per_tick_limit", 2)
    clean_db.commit()

    _raw_item(clean_db, source, "a", external_id="a-guid")
    _raw_item(clean_db, source, "b", external_id="b-guid")
    _raw_item(clean_db, source, "c", external_id="c-guid")

    stats = run_clustering_cycle(clean_db)

    assert stats == {"attached": 0, "created": 2}
    clustered = [item for item in clean_db.query(RawItem).all() if item.cluster_id is not None]
    unclustered = [item for item in clean_db.query(RawItem).all() if item.cluster_id is None]
    assert len(clustered) == 2
    assert len(unclustered) == 1
    assert unclustered[0].title == "c"


def test_already_clustered_items_are_left_alone(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    clean_db.refresh(cluster)

    item = _raw_item(clean_db, source, "already-done", embedding=TOPIC_A, cluster_id=cluster.id)

    assert unclustered_raw_items(clean_db, limit=200) == []
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


def test_candidate_clusters_include_old_events(clean_db):
    source = _source(clean_db)
    old = NewsCluster(embedding=TOPIC_A, trace_id="t")
    clean_db.add(old)
    clean_db.commit()
    clean_db.execute(
        NewsCluster.__table__.update()
        .where(NewsCluster.id == old.id)
        .values(created_at=datetime.now(UTC) - timedelta(days=30))
    )
    clean_db.commit()

    _raw_item(clean_db, source, "old-item", embedding=TOPIC_A, cluster_id=old.id)

    assert old.id in {cluster.id for cluster in candidate_clusters(clean_db)}


def test_candidate_clusters_do_not_load_historical_article_text(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    _raw_item(
        clean_db,
        source,
        "large-old-item",
        embedding=TOPIC_A,
        cluster_id=cluster.id,
        body="x" * 100_000,
    )
    clean_db.expire_all()

    candidate = candidate_clusters(clean_db)[0]

    assert len(candidate.raw_items) == 1
    unloaded = inspect(candidate.raw_items[0]).unloaded
    assert {"body", "title", "source"}.issubset(unloaded)


def test_match_uses_any_existing_item_embedding(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_B, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    _raw_item(clean_db, source, "matching-follow-up", embedding=TOPIC_A, cluster_id=cluster.id)
    incoming = _raw_item(clean_db, source, "same-event", embedding=TOPIC_A)

    result = cluster_raw_item(clean_db, incoming, candidate_clusters(clean_db))

    assert result.id == cluster.id
    assert incoming.cluster_id == cluster.id


def test_borderline_match_requires_llm_confirmation(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A_VARIANT, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    incoming = _raw_item(clean_db, source, "possible-duplicate", embedding=TOPIC_A)
    calls: list[tuple] = []

    result = cluster_raw_item(
        clean_db,
        incoming,
        candidate_clusters(clean_db),
        confirm_duplicate=lambda item, candidate: calls.append((item, candidate)) or True,
    )

    assert result.id == cluster.id
    assert calls == [(incoming, cluster)]


def test_rejected_borderline_match_creates_new_cluster(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A_VARIANT, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    incoming = _raw_item(clean_db, source, "different-event", embedding=TOPIC_A)

    result = cluster_raw_item(
        clean_db,
        incoming,
        candidate_clusters(clean_db),
        confirm_duplicate=lambda *_: False,
    )

    assert result.id != cluster.id
    assert incoming.cluster_id == result.id


def test_confirmation_checks_next_candidate_after_rejection(clean_db):
    source = _source(clean_db)
    first = NewsCluster(embedding=TOPIC_A_VARIANT, trace_id="first")
    second = NewsCluster(embedding=TOPIC_A_SECOND_VARIANT, trace_id="second")
    clean_db.add_all([first, second])
    clean_db.commit()
    incoming = _raw_item(clean_db, source, "same-event", embedding=TOPIC_A)
    calls = []

    result = cluster_raw_item(
        clean_db,
        incoming,
        candidate_clusters(clean_db),
        confirm_duplicate=lambda _, candidate: calls.append(candidate.id)
        or candidate.id == second.id,
    )

    assert result is not None
    assert result.id == second.id
    assert calls == [first.id, second.id]


def test_confirmation_outage_defers_ambiguous_item(clean_db):
    source = _source(clean_db)
    cluster = NewsCluster(embedding=TOPIC_A_VARIANT, trace_id="t")
    clean_db.add(cluster)
    clean_db.commit()
    incoming = _raw_item(clean_db, source, "possible-duplicate", embedding=TOPIC_A)

    result = cluster_raw_item(
        clean_db,
        incoming,
        candidate_clusters(clean_db),
        confirm_duplicate=lambda *_: None,
    )

    assert result is None
    assert incoming.cluster_id is None
