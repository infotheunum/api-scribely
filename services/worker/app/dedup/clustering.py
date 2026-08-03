from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.tracing import new_trace_id
from db.models import NewsCluster, RawItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.dedup.embeddings import (
    SIMILARITY_THRESHOLD,
    cosine_similarity,
    embed_text,
    embedding_text,
)

logger = logging.getLogger(__name__)

# News events are worth cross-referencing against for a few days after
# they first appear — old clusters shouldn't keep absorbing unrelated
# later coverage that happens to use similar wording (ТЗ §4.2).
CLUSTER_WINDOW = timedelta(hours=72)


def unclustered_raw_items(db: Session, *, limit: int = 200) -> list[RawItem]:
    return list(
        db.scalars(
            select(RawItem)
            .where(RawItem.cluster_id.is_(None))
            .order_by(RawItem.fetched_at)
            .limit(limit)
        )
    )


def recent_clusters(db: Session, *, now: datetime | None = None) -> list[NewsCluster]:
    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(NewsCluster).where(
                NewsCluster.created_at >= now - CLUSTER_WINDOW,
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


def cluster_raw_item(db: Session, raw_item: RawItem, clusters: list[NewsCluster]) -> NewsCluster:
    """Assigns one RawItem to the best-matching recent cluster (cross-
    language — the embedding model is multilingual, ТЗ §4.2), or starts a
    new cluster if nothing scores above SIMILARITY_THRESHOLD. Mutates and
    returns the cluster; `clusters` is extended in place so later items in
    the same batch can match newly-created clusters too."""
    if raw_item.embedding is None:
        raw_item.embedding = embed_text(embedding_text(raw_item.title, raw_item.body))

    best_cluster, score = _best_match(raw_item.embedding, clusters)
    if best_cluster is not None and score >= SIMILARITY_THRESHOLD:
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
    clusters = recent_clusters(db)
    stats = {"attached": 0, "created": 0}
    initial_cluster_ids = {c.id for c in clusters}

    for raw_item in unclustered_raw_items(db):
        cluster = cluster_raw_item(db, raw_item, clusters)
        if cluster.id in initial_cluster_ids:
            stats["attached"] += 1
        else:
            stats["created"] += 1
            initial_cluster_ids.add(cluster.id)

    db.commit()
    return stats
