from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from db.enums import TopicStatus
from db.models import NewsCluster
from sqlalchemy import select
from sqlalchemy.orm import Session

# Same relevance window as clustering/scoring — a cluster older than this
# has already decayed to zero freshness score anyway (ТЗ §4.20 TTL/aging).
SELECTION_WINDOW = timedelta(hours=72)

# Soft ceiling of the 90-110/day target (ТЗ §1, §4.3) — "при превышении
# верхней границы низкоприоритетные кластеры не отправляются на рерайт".
# The actual daily-published count doesn't exist yet (Publish is Phase
# 7); Phase 4's dispatch loop is expected to pass
# `limit=110-already_published_today` once that count is real. Until
# then this is the upper bound taken on its own.
DEFAULT_LIMIT = 110

# No single source should fill more than this share of the selected
# queue (ТЗ §4.3 fairness quota) — a noisy Tier 1 RSS feed with 30
# articles/hour shouldn't crowd out everything else.
DEFAULT_FAIRNESS_CAP_RATIO = 0.3


def select_top_clusters(
    db: Session,
    *,
    limit: int = DEFAULT_LIMIT,
    fairness_cap_ratio: float = DEFAULT_FAIRNESS_CAP_RATIO,
    now: datetime | None = None,
) -> list[NewsCluster]:
    """Priority-ordered, fairness-capped selection of in-topic clusters —
    "what would be sent to rewrite right now" (ТЗ §4.3). Pure query, no
    side effects: Phase 4 is what actually dispatches:
    RewriteCluster excludes clusters that already have a Draft once that
    table is populated, so calling this repeatedly is safe.
    """
    now = now or datetime.now(UTC)
    candidates = db.scalars(
        select(NewsCluster)
        .where(
            NewsCluster.topic_status == TopicStatus.IN_TOPIC,
            NewsCluster.created_at >= now - SELECTION_WINDOW,
        )
        .order_by(NewsCluster.priority_score.desc())
    ).all()

    max_per_source = max(1, int(limit * fairness_cap_ratio))
    per_source_count: dict = defaultdict(int)
    selected: list[NewsCluster] = []

    for cluster in candidates:
        if len(selected) >= limit:
            break
        cluster_source_ids = {item.source_id for item in cluster.raw_items}
        if any(per_source_count[sid] >= max_per_source for sid in cluster_source_ids):
            continue
        selected.append(cluster)
        for sid in cluster_source_ids:
            per_source_count[sid] += 1

    return selected
