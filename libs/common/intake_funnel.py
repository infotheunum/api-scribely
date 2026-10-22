"""RSS → rewrite intake funnel for diagnosing empty dispatch.

Answers: over the last N hours, how many feed items arrived, and why none
(or few) became rewrite-eligible undrafted clusters. Includes sample titles
per drop bucket so editors can see what the 200 feeds actually produced.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from db.app_settings import get_setting
from db.enums import TopicStatus
from db.models import ClusterQuarantine, Draft, NewsCluster, RawItem, Source
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from common.generation_hours import DEFAULT_TIMEZONE, resolve_tz

MAX_AGE_HOURS_SETTING_KEY = "ingestion.max_item_age_hours"
DEFAULT_MAX_AGE_HOURS = 24.0

BUCKET_ORDER = (
    "not_clustered",
    "quarantined",
    "on_drafted_cluster",
    "out_of_topic",
    "topic_pending",
    "in_topic_stale",
    "in_topic_fresh_undrafted",
)

BUCKET_LABELS_RU = {
    "not_clustered": "Ещё не в кластере (очередь dedup)",
    "quarantined": "Кластер в карантине",
    "on_drafted_cluster": "Прилипло к сюжету, у которого уже есть Draft (в т.ч. reject)",
    "out_of_topic": "Кластер вне тем редакции",
    "topic_pending": "Тема ещё не классифицирована",
    "in_topic_stale": "In-topic, но вне окна свежести (published/fetched)",
    "in_topic_fresh_undrafted": "Готово к рерайту (свежий undrafted in-topic)",
}


def _age_hours(db: Session) -> float:
    raw = get_setting(db, MAX_AGE_HOURS_SETTING_KEY, DEFAULT_MAX_AGE_HOURS)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        hours = DEFAULT_MAX_AGE_HOURS
    return max(1.0, hours)


def _effective_at(item: RawItem) -> datetime:
    return item.published_at or item.fetched_at


def _sample_row(item: RawItem, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "title": (item.title or "")[:240],
        "source": item.source.name if item.source else None,
        "url": item.url,
        "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "cluster_id": str(item.cluster_id) if item.cluster_id else None,
    }
    if extra:
        row.update(extra)
    return row


def build_intake_funnel(
    db: Session,
    *,
    hours: float = 4.0,
    sample_limit: int = 15,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate feed intake over ``hours`` and classify each RawItem."""
    now = now or datetime.now(UTC)
    hours = max(1.0, min(168.0, float(hours)))
    sample_limit = max(1, min(50, int(sample_limit)))
    window_start = now - timedelta(hours=hours)
    editorial_age_h = _age_hours(db)
    freshness_cutoff = now - timedelta(hours=editorial_age_h)

    active_sources = int(
        db.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.is_active.is_(True), Source.deleted_at.is_(None))
        )
        or 0
    )
    polled_sources = int(
        db.scalar(
            select(func.count())
            .select_from(Source)
            .where(
                Source.is_active.is_(True),
                Source.deleted_at.is_(None),
                Source.last_polled_at.is_not(None),
                Source.last_polled_at >= window_start,
            )
        )
        or 0
    )

    items = list(
        db.scalars(
            select(RawItem)
            .where(RawItem.fetched_at >= window_start, RawItem.fetched_at < now)
            .options(selectinload(RawItem.source), selectinload(RawItem.cluster))
            .order_by(RawItem.fetched_at.desc())
        )
    )

    cluster_ids = {item.cluster_id for item in items if item.cluster_id}
    drafted: dict[UUID, str] = {}
    if cluster_ids:
        for cluster_id, status in db.execute(
            select(Draft.cluster_id, Draft.status).where(Draft.cluster_id.in_(cluster_ids))
        ):
            # One draft per cluster in practice; keep first status seen.
            drafted.setdefault(cluster_id, str(status))

    quarantined: set[UUID] = set()
    if cluster_ids:
        quarantined = set(
            db.scalars(
                select(ClusterQuarantine.cluster_id).where(
                    ClusterQuarantine.cluster_id.in_(cluster_ids),
                    ClusterQuarantine.released_at.is_(None),
                )
            )
        )

    # Newest effective stamp per cluster (among ALL raw items on that cluster,
    # not only those fetched in-window) — matches dispatch freshness.
    newest_by_cluster: dict[UUID, datetime] = {}
    if cluster_ids:
        rows = db.execute(
            select(
                RawItem.cluster_id,
                func.max(func.coalesce(RawItem.published_at, RawItem.fetched_at)),
            )
            .where(RawItem.cluster_id.in_(cluster_ids))
            .group_by(RawItem.cluster_id)
        ).all()
        for cluster_id, stamp in rows:
            if cluster_id is not None and stamp is not None:
                newest_by_cluster[cluster_id] = stamp

    buckets: dict[str, list[RawItem]] = {name: [] for name in BUCKET_ORDER}
    draft_status_counts: dict[str, int] = defaultdict(int)
    per_source: dict[str, int] = defaultdict(int)

    for item in items:
        if item.source:
            per_source[item.source.name] += 1

        if item.cluster_id is None or item.cluster is None:
            buckets["not_clustered"].append(item)
            continue

        cid = item.cluster_id
        if cid in quarantined:
            buckets["quarantined"].append(item)
            continue

        if cid in drafted:
            buckets["on_drafted_cluster"].append(item)
            draft_status_counts[drafted[cid]] += 1
            continue

        status = item.cluster.topic_status
        if status == TopicStatus.OUT_OF_TOPIC:
            buckets["out_of_topic"].append(item)
            continue
        if status != TopicStatus.IN_TOPIC:
            buckets["topic_pending"].append(item)
            continue

        newest = newest_by_cluster.get(cid) or _effective_at(item)
        if newest < freshness_cutoff:
            buckets["in_topic_stale"].append(item)
            continue

        buckets["in_topic_fresh_undrafted"].append(item)

    counts = {name: len(rows) for name, rows in buckets.items()}
    samples: dict[str, list[dict[str, Any]]] = {}
    for name, rows in buckets.items():
        sample_rows: list[dict[str, Any]] = []
        for it in rows[:sample_limit]:
            extra = None
            if name == "on_drafted_cluster" and it.cluster_id is not None:
                extra = {"draft_status": drafted.get(it.cluster_id)}
            sample_rows.append(_sample_row(it, extra=extra))
        samples[name] = sample_rows

    new_clusters = int(
        db.scalar(
            select(func.count())
            .select_from(NewsCluster)
            .where(NewsCluster.created_at >= window_start, NewsCluster.created_at < now)
        )
        or 0
    )
    new_undrafted_in_topic = int(
        db.scalar(
            select(func.count())
            .select_from(NewsCluster)
            .where(
                NewsCluster.created_at >= window_start,
                NewsCluster.created_at < now,
                NewsCluster.topic_status == TopicStatus.IN_TOPIC,
                ~exists(select(Draft.id).where(Draft.cluster_id == NewsCluster.id)),
            )
        )
        or 0
    )

    top_sources = sorted(
        ({"source": name, "items": n} for name, n in per_source.items()),
        key=lambda row: (-row["items"], row["source"]),
    )[:25]

    sources_with_items = len(per_source)
    tz = resolve_tz(DEFAULT_TIMEZONE)

    return {
        "window": {
            "hours": hours,
            "from": window_start.isoformat(),
            "to": now.isoformat(),
            "timezone_note": DEFAULT_TIMEZONE,
            "local_from": window_start.astimezone(tz).isoformat(),
            "local_to": now.astimezone(tz).isoformat(),
        },
        "settings": {
            "ingestion_max_item_age_hours": editorial_age_h,
            "freshness_cutoff": freshness_cutoff.isoformat(),
        },
        "sources": {
            "active": active_sources,
            "polled_in_window": polled_sources,
            "with_new_items_in_window": sources_with_items,
            "top_by_items": top_sources,
        },
        "totals": {
            "raw_items_fetched": len(items),
            "new_clusters_created": new_clusters,
            "new_undrafted_in_topic_clusters": new_undrafted_in_topic,
            "rewrite_eligible_items": counts["in_topic_fresh_undrafted"],
        },
        "drop_buckets": {
            name: {
                "label_ru": BUCKET_LABELS_RU[name],
                "count": counts[name],
                "sample_titles": samples[name],
            }
            for name in BUCKET_ORDER
        },
        "on_drafted_by_status": dict(sorted(draft_status_counts.items())),
        "verdict": _verdict(len(items), counts),
    }


def _verdict(total: int, counts: dict[str, int]) -> str:
    if total == 0:
        return (
            "За окно не сохранено ни одного RawItem — либо фиды молчат / "
            "не поллились, либо все GUID уже были в базе (идемпотентный skip)."
        )
    eligible = counts.get("in_topic_fresh_undrafted", 0)
    if eligible > 0:
        return (
            f"Есть {eligible} свежих undrafted in-topic айтемов — dispatch "
            "должен их брать. Если dispatched=0, смотри hourly cap / failed queue / in-flight."
        )
    drafted = counts.get("on_drafted_cluster", 0)
    stale = counts.get("in_topic_stale", 0)
    oot = counts.get("out_of_topic", 0)
    parts = []
    if drafted:
        parts.append(f"{drafted} прилипли к уже обработанным сюжетам")
    if stale:
        parts.append(f"{stale} in-topic но старше окна свежести")
    if oot:
        parts.append(f"{oot} вне тем")
    if counts.get("not_clustered"):
        parts.append(f"{counts['not_clustered']} ещё не кластеризованы")
    if not parts:
        parts.append("нет rewrite-eligible айтемов")
    return "Почему пусто: " + "; ".join(parts) + "."
