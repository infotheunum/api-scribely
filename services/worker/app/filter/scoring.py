from __future__ import annotations

from datetime import UTC, datetime

from db.models import NewsCluster
from worker_app.filter.freshness import cluster_newest_effective_at

# Priority = cross-verification signal + source authority + freshness
# (ТЗ §4.3: "количество источников в кластере + уровень источника (Tier)
# + свежесть"). Weights are a reasonable MVP starting point, not a tuned
# model — nothing here claims to be more precise than that.
SOURCE_COUNT_WEIGHT = 10.0
TIER_WEIGHT = 5.0
FRESHNESS_WEIGHT = 20.0
# Align with ingestion.max_item_age_hours default (1–2 day editorial window):
# freshness score hits zero as the item leaves the rewrite-eligible window.
FRESHNESS_HALF_LIFE_HOURS = 48.0


def compute_priority_score(cluster: NewsCluster, *, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)

    distinct_sources = {item.source_id for item in cluster.raw_items}
    source_score = len(distinct_sources) * SOURCE_COUNT_WEIGHT

    tiers = [item.source.tier for item in cluster.raw_items if item.source is not None]
    # Lower tier number = more authoritative per Приложение 1 политики —
    # tier 1 scores highest, tier 6 lowest. int(tier) since SourceTier is
    # an IntEnum but comparisons against the raw weight formula read
    # clearer as plain ints.
    best_tier = min((int(t) for t in tiers), default=6)
    tier_score = (7 - best_tier) * TIER_WEIGHT

    # Prefer article publish time over cluster ingest time so delayed RSS
    # history (or first poll of a new feed) does not fake freshness.
    anchor = cluster_newest_effective_at(cluster) or cluster.created_at
    age_hours = (now - anchor).total_seconds() / 3600
    freshness_score = FRESHNESS_WEIGHT * max(0.0, 1 - age_hours / FRESHNESS_HALF_LIFE_HOURS)

    return source_score + tier_score + freshness_score
