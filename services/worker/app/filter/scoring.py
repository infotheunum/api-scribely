from __future__ import annotations

from datetime import UTC, datetime

from db.models import NewsCluster

# Priority = cross-verification signal + source authority + freshness
# (ТЗ §4.3: "количество источников в кластере + уровень источника (Tier)
# + свежесть"). Weights are a reasonable MVP starting point, not a tuned
# model — nothing here claims to be more precise than that.
SOURCE_COUNT_WEIGHT = 10.0
TIER_WEIGHT = 5.0
FRESHNESS_WEIGHT = 20.0
# Matches the clustering window (worker_app/dedup/clustering.py) — a
# cluster's freshness component decays to zero by the time it drops out
# of the cross-language matching window anyway.
FRESHNESS_HALF_LIFE_HOURS = 72.0


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

    age_hours = (now - cluster.created_at).total_seconds() / 3600
    freshness_score = FRESHNESS_WEIGHT * max(0.0, 1 - age_hours / FRESHNESS_HALF_LIFE_HOURS)

    return source_score + tier_score + freshness_score
