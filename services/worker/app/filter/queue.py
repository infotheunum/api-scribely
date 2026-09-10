from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from db.app_settings import get_setting
from db.enums import TopicStatus
from db.models import NewsCluster
from sqlalchemy import select
from sqlalchemy.orm import Session

# Same relevance window as clustering/scoring — a cluster older than this
# has already decayed to zero freshness score anyway (ТЗ §4.20 TTL/aging).
SELECTION_WINDOW = timedelta(hours=72)

# Maximum number of drafts per editorial day. Dispatch also counts drafts
# already created today, so this is a hard cap rather than a queue hint.
# Overridable at runtime through AppSetting (ТЗ §4.21).
DEFAULT_LIMIT = 10
LIMIT_SETTING_KEY = "queue.daily_limit"

# No single source should fill more than this share of the selected
# queue (ТЗ §4.3 fairness quota) — a noisy Tier 1 RSS feed with 30
# articles/hour shouldn't crowd out everything else.
DEFAULT_FAIRNESS_CAP_RATIO = 0.3
FAIRNESS_CAP_RATIO_SETTING_KEY = "queue.fairness_cap_ratio"


def select_top_clusters(
    db: Session,
    *,
    limit: int | None = None,
    fairness_cap_ratio: float | None = None,
    exclude_cluster_ids: set | None = None,
    now: datetime | None = None,
) -> list[NewsCluster]:
    """Priority-ordered, fairness-capped selection of in-topic clusters —
    "what would be sent to rewrite right now" (ТЗ §4.3). Pure query, no
    side effects: Phase 4 is what actually dispatches:
    RewriteCluster excludes clusters that already have a Draft once that
    table is populated, so calling this repeatedly is safe.

    `limit`/`fairness_cap_ratio` default to the current AppSetting value
    (ТЗ §4.21) when not passed explicitly — pass explicitly only to
    override for a specific call (e.g. tests).
    """
    if limit is None:
        limit = get_setting(db, LIMIT_SETTING_KEY, DEFAULT_LIMIT)
    if fairness_cap_ratio is None:
        fairness_cap_ratio = get_setting(
            db, FAIRNESS_CAP_RATIO_SETTING_KEY, DEFAULT_FAIRNESS_CAP_RATIO
        )
    now = now or datetime.now(UTC)
    conditions = [
        NewsCluster.topic_status == TopicStatus.IN_TOPIC,
        NewsCluster.created_at >= now - SELECTION_WINDOW,
    ]
    if exclude_cluster_ids:
        conditions.append(NewsCluster.id.not_in(exclude_cluster_ids))
    candidates = db.scalars(
        select(NewsCluster).where(*conditions).order_by(NewsCluster.priority_score.desc())
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
