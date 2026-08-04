from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from db.enums import TopicStatus
from db.models import NewsCluster
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.filter.scoring import compute_priority_score
from worker_app.filter.topics import active_topics, classify, compile_topics

logger = logging.getLogger(__name__)

# Same relevance window as clustering/selection — no point rescoring a
# cluster that's already aged out of consideration everywhere else.
RESCORE_WINDOW = timedelta(hours=72)


def _cluster_text(cluster: NewsCluster) -> str:
    parts = [item.title or "" for item in cluster.raw_items]
    parts += [item.body for item in cluster.raw_items if item.body]
    return "\n".join(parts)


def classify_pending_clusters(db: Session) -> int:
    """Topic-filters every not-yet-classified cluster (ТЗ §4.3, redpolicy
    §1.4) — rule-based on purpose, this gate runs before anything ever
    reaches the LLM in Phase 4."""
    pending = db.scalars(
        select(NewsCluster).where(NewsCluster.topic_status == TopicStatus.PENDING)
    ).all()
    compiled_topics = compile_topics(active_topics(db))
    for cluster in pending:
        in_topic, topic = classify(_cluster_text(cluster), compiled_topics)
        cluster.topic_status = TopicStatus.IN_TOPIC if in_topic else TopicStatus.OUT_OF_TOPIC
        cluster.topic = topic
    db.commit()
    return len(pending)


def rescore_recent_clusters(db: Session, *, now: datetime | None = None) -> int:
    """Priority score decays with age (ТЗ §4.20 TTL/aging), so it's
    recomputed for the whole recent window each tick, not just for
    newly-classified clusters."""
    now = now or datetime.now(UTC)
    recent = db.scalars(
        select(NewsCluster).where(NewsCluster.created_at >= now - RESCORE_WINDOW)
    ).all()
    for cluster in recent:
        cluster.priority_score = compute_priority_score(cluster, now=now)
    db.commit()
    return len(recent)


def run_filter_cycle(db: Session) -> dict[str, int]:
    classified = classify_pending_clusters(db)
    rescored = rescore_recent_clusters(db)
    return {"classified": classified, "rescored": rescored}
