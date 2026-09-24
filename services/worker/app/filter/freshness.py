"""Editorial freshness window for raw items and clusters.

Selection and scoring historically used ``NewsCluster.created_at`` (when we
ingested / clustered). That treats a week-old RSS item ingested today as
"fresh" — which is wrong after bulk source onboarding. Effective age is
``coalesce(published_at, fetched_at)`` on the newest raw item in the cluster
(ТЗ §4.3 / §4.20 freshness).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.app_settings import get_setting
from db.models import NewsCluster, RawItem
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

# Editorial window: only news from roughly the last 1–2 days are worth
# rewrite (ingest + dispatch). Overridable via AppSetting.
DEFAULT_MAX_AGE_HOURS = 48.0
MAX_AGE_HOURS_SETTING_KEY = "ingestion.max_item_age_hours"


def max_item_age_hours(db: Session) -> float:
    raw = get_setting(db, MAX_AGE_HOURS_SETTING_KEY, DEFAULT_MAX_AGE_HOURS)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        hours = DEFAULT_MAX_AGE_HOURS
    return max(1.0, hours)


def max_item_age_window(db: Session) -> timedelta:
    return timedelta(hours=max_item_age_hours(db))


def effective_item_at(item: RawItem) -> datetime:
    return item.published_at or item.fetched_at


def item_is_fresh(item: RawItem, *, now: datetime, window: timedelta) -> bool:
    return effective_item_at(item) >= now - window


def cluster_newest_effective_at(cluster: NewsCluster) -> datetime | None:
    stamps = [effective_item_at(item) for item in cluster.raw_items]
    return max(stamps) if stamps else None


def cluster_is_fresh(cluster: NewsCluster, *, now: datetime, window: timedelta) -> bool:
    newest = cluster_newest_effective_at(cluster)
    if newest is None:
        return cluster.created_at >= now - window
    return newest >= now - window


def raw_item_effective_at_expr() -> ColumnElement:
    return func.coalesce(RawItem.published_at, RawItem.fetched_at)


def fresh_unclustered_raw_items(
    db: Session, *, limit: int, now: datetime | None = None
) -> list[RawItem]:
    """Unclustered items still inside the editorial freshness window."""
    now = now or datetime.now(UTC)
    cutoff = now - max_item_age_window(db)
    return list(
        db.scalars(
            select(RawItem)
            .where(
                RawItem.cluster_id.is_(None),
                raw_item_effective_at_expr() >= cutoff,
            )
            .order_by(RawItem.fetched_at)
            .limit(limit)
        )
    )
