from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.tracing import new_trace_id
from db.app_settings import get_setting
from db.models import NewsCluster, RawItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.dedup.embeddings import (
    DEFAULT_EMBED_BATCH_SIZE,
    EMBED_BATCH_SIZE_SETTING_KEY,
    SIMILARITY_THRESHOLD,
    cosine_similarity,
    embed_texts,
    embedding_text,
)

logger = logging.getLogger(__name__)

# News events are worth cross-referencing against for a few days after
# they first appear — old clusters shouldn't keep absorbing unrelated
# later coverage that happens to use similar wording (ТЗ §4.2). Both
# constants below are AppSetting-overridable at runtime (ТЗ §4.21).
CLUSTER_WINDOW = timedelta(hours=72)
CLUSTER_WINDOW_HOURS_SETTING_KEY = "dedup.cluster_window_hours"
SIMILARITY_THRESHOLD_SETTING_KEY = "dedup.similarity_threshold"
CLUSTER_PER_TICK_LIMIT_KEY = "dedup.cluster_per_tick_limit"
DEFAULT_CLUSTER_PER_TICK_LIMIT = 20


def _cluster_per_tick_limit(db: Session) -> int:
    raw = get_setting(db, CLUSTER_PER_TICK_LIMIT_KEY, DEFAULT_CLUSTER_PER_TICK_LIMIT)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = DEFAULT_CLUSTER_PER_TICK_LIMIT
    return max(1, limit)


def _embed_batch_size(db: Session) -> int:
    raw = get_setting(db, EMBED_BATCH_SIZE_SETTING_KEY, DEFAULT_EMBED_BATCH_SIZE)
    try:
        size = int(raw)
    except (TypeError, ValueError):
        size = DEFAULT_EMBED_BATCH_SIZE
    return max(1, size)


def unclustered_raw_items(db: Session, *, limit: int) -> list[RawItem]:
    return list(
        db.scalars(
            select(RawItem)
            .where(RawItem.cluster_id.is_(None))
            .order_by(RawItem.fetched_at)
            .limit(limit)
        )
    )


def recent_clusters(
    db: Session, *, now: datetime | None = None, window: timedelta | None = None
) -> list[NewsCluster]:
    now = now or datetime.now(UTC)
    if window is None:
        hours = get_setting(
            db, CLUSTER_WINDOW_HOURS_SETTING_KEY, CLUSTER_WINDOW.total_seconds() / 3600
        )
        window = timedelta(hours=hours)
    return list(
        db.scalars(
            select(NewsCluster).where(
                NewsCluster.created_at >= now - window,
                NewsCluster.embedding.is_not(None),
            )
        )
    )


def _best_match(
    embedding: list[float], clusters: list[NewsCluster]
) -> tuple[NewsCluster | None, float]:
    best_cluster: NewsCluster | None = None
    best_score = 0.0
    for cluster in clusters:
        score = cosine_similarity(embedding, cluster.embedding)
        if score > best_score:
            best_cluster, best_score = cluster, score
    return best_cluster, best_score


def _prefetch_embeddings(db: Session, raw_items: list[RawItem]) -> None:
    pending: list[tuple[RawItem, str]] = []
    for raw_item in raw_items:
        if raw_item.embedding is None:
            pending.append((raw_item, embedding_text(raw_item.title, raw_item.body)))
    if not pending:
        return
    texts = [text for _, text in pending]
    vectors = embed_texts(texts, batch_size=_embed_batch_size(db))
    for (raw_item, _), vector in zip(pending, vectors, strict=True):
        raw_item.embedding = vector


def cluster_raw_item(
    db: Session,
    raw_item: RawItem,
    clusters: list[NewsCluster],
    *,
    similarity_threshold: float | None = None,
) -> NewsCluster:
    """Assigns one RawItem to the best-matching recent cluster (cross-
    language — the embedding model is multilingual, ТЗ §4.2), or starts a
    new cluster if nothing scores above the similarity threshold. Mutates
    and returns the cluster; `clusters` is extended in place so later
    items in the same batch can match newly-created clusters too."""
    if similarity_threshold is None:
        similarity_threshold = get_setting(
            db, SIMILARITY_THRESHOLD_SETTING_KEY, SIMILARITY_THRESHOLD
        )
    if raw_item.embedding is None:
        raise ValueError(f"raw_item {raw_item.id} has no embedding — prefetch first")

    best_cluster, score = _best_match(raw_item.embedding, clusters)
    if best_cluster is not None and score >= similarity_threshold:
        raw_item.cluster_id = best_cluster.id
        logger.info(
            "raw_item %s matched cluster %s (score=%.3f)", raw_item.id, best_cluster.id, score
        )
        return best_cluster

    new_cluster = NewsCluster(embedding=raw_item.embedding, trace_id=new_trace_id())
    db.add(new_cluster)
    db.flush()  # need new_cluster.id before assigning the FK below
    raw_item.cluster_id = new_cluster.id
    clusters.append(new_cluster)
    logger.info("raw_item %s started new cluster %s", raw_item.id, new_cluster.id)
    return new_cluster


def run_clustering_cycle(db: Session) -> dict[str, int]:
    similarity_threshold = get_setting(db, SIMILARITY_THRESHOLD_SETTING_KEY, SIMILARITY_THRESHOLD)
    limit = _cluster_per_tick_limit(db)
    raw_items = unclustered_raw_items(db, limit=limit)
    if not raw_items:
        return {"attached": 0, "created": 0}

    _prefetch_embeddings(db, raw_items)

    clusters = recent_clusters(db)
    stats = {"attached": 0, "created": 0}
    initial_cluster_ids = {c.id for c in clusters}

    for raw_item in raw_items:
        cluster = cluster_raw_item(
            db, raw_item, clusters, similarity_threshold=similarity_threshold
        )
        if cluster.id in initial_cluster_ids:
            stats["attached"] += 1
        else:
            stats["created"] += 1
            initial_cluster_ids.add(cluster.id)

    db.commit()
    return stats
