from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

import grpc
from common.generation_hours import (
    effective_daily_limit,
    manual_burst_remaining,
    record_manual_burst_draft,
)
from common.grpc_client import build_rewrite_channel, rewrite_stub
from common.llm_token_totals import record_token_usage
from common.pipeline_telemetry import record_dispatch_cycle_result
from common.token_usage import TokenUsage
from common.tracing import get_trace_id, new_trace_id, set_trace_id
from db.app_settings import get_setting, set_setting
from db.enums import DraftRevisionKind, QuarantineReason
from db.models import ClusterContext, ClusterQuarantine, Draft, NewsCluster
from scribely.rewrite.v1 import rewrite_pb2
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from worker_app.dispatch.draft_apply import apply_rewrite_content
from worker_app.filter.queue import select_top_clusters
from worker_app.settings import WorkerSettings

logger = logging.getLogger(__name__)

# Free-tier LLM latency (~45-95s per Enrich+Rewrite round-trip,
# live-observed against real OpenRouter) dwarfs the 60s poll tick that
# this pipeline shares with ingestion/clustering/filtering — a small
# per-tick cap keeps one dispatch burst from starving the rest of the
# tick. The daily cap is enforced separately against Draft.created_at.
#
# Set to 1 (not the originally-planned 3) for the first Railway deploy of
# this dispatcher on purpose: worker had already accumulated ~140
# undrafted in-topic clusters over Phases 1-3's runtime, and at 3/tick
# that backlog would burn through free-tier OpenRouter quota in one
# unattended ~47-minute burst right after deploy. At 1/tick it's ~2.5h
# instead — safer for the very first live run. Now a runtime-editable
# AppSetting (ТЗ §4.21, Фаза 5) — this constant is only the fallback
# default before `dispatch.batch_size` is ever seeded.
DISPATCH_BATCH_SIZE = 1
BATCH_SIZE_SETTING_KEY = "dispatch.batch_size"
EDITORIAL_TIMEZONE = ZoneInfo("Europe/Minsk")
FAILED_QUEUE_SETTING_KEY = "dispatch.failed_cluster_queue"
FAILED_QUEUE_DEFER_HOURS = 6
TARGET_PER_HOUR_SETTING_KEY = "dispatch.target_per_hour"
DEFAULT_TARGET_PER_HOUR = 18

# The Railway worker is a single replica.  Three APScheduler dispatch jobs
# share this process; reserve a cluster while its slow LLM call is in flight
# so simultaneous ticks cannot generate the same draft twice.
_IN_FLIGHT_CLUSTER_IDS: set[uuid.UUID] = set()
_IN_FLIGHT_CLUSTER_IDS_LOCK = Lock()


def _already_drafted_cluster_ids(db: Session) -> set:
    return set(db.scalars(select(Draft.cluster_id)))


def _active_quarantined_cluster_ids(db: Session) -> set:
    return set(
        db.scalars(
            select(ClusterQuarantine.cluster_id).where(ClusterQuarantine.released_at.is_(None))
        )
    )


def _quarantine_cluster(
    db: Session, cluster_id: uuid.UUID, reason: QuarantineReason, evidence: str
) -> None:
    """Record an editorial stop once; active quarantines are intentionally idempotent."""
    row = db.scalar(select(ClusterQuarantine).where(ClusterQuarantine.cluster_id == cluster_id))
    if row is None:
        db.add(ClusterQuarantine(cluster_id=cluster_id, reason=reason, evidence=evidence[:4000]))
        return
    if row.released_at is not None:
        row.released_at = None
        row.released_by = None
    row.reason = reason
    row.evidence = evidence[:4000]


def _deferred_cluster_ids(db: Session, *, now: datetime) -> set[uuid.UUID]:
    raw = get_setting(db, FAILED_QUEUE_SETTING_KEY, {})
    if not isinstance(raw, dict):
        return set()
    deferred: set[uuid.UUID] = set()
    for value in raw.values():
        if not isinstance(value, dict):
            continue
        try:
            cluster_id = uuid.UUID(str(value["cluster_id"]))
            retry_after = datetime.fromisoformat(str(value["retry_after"]))
        except (KeyError, TypeError, ValueError):
            continue
        if retry_after > now:
            deferred.add(cluster_id)
    return deferred


def _record_failed_cluster(db: Session, cluster_id: uuid.UUID, details: str) -> None:
    raw = get_setting(db, FAILED_QUEUE_SETTING_KEY, {})
    queue = raw if isinstance(raw, dict) else {}
    key = str(cluster_id)
    previous = queue.get(key, {}) if isinstance(queue.get(key), dict) else {}
    failures = int(previous.get("failures", 0)) + 1
    now = datetime.now(UTC)
    retry_after = now if failures < 2 else now + timedelta(hours=FAILED_QUEUE_DEFER_HOURS)
    queue[key] = {
        "cluster_id": key,
        "failures": failures,
        "retry_after": retry_after.isoformat(),
        "last_error": details[:800],
    }
    set_setting(
        db,
        FAILED_QUEUE_SETTING_KEY,
        queue,
        description="Clusters deferred for six hours after two failed rewrite attempts.",
    )


def _drafts_created_today(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    local_now = now.astimezone(EDITORIAL_TIMEZONE)
    local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_day_start.astimezone(UTC)
    return int(
        db.scalar(select(func.count()).select_from(Draft).where(Draft.created_at >= day_start)) or 0
    )


def _drafts_created_this_hour(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    return int(
        db.scalar(select(func.count()).select_from(Draft).where(Draft.created_at >= hour_start))
        or 0
    )


def _reserve_candidates(candidates: list[NewsCluster], *, limit: int) -> list[NewsCluster]:
    reserved: list[NewsCluster] = []
    with _IN_FLIGHT_CLUSTER_IDS_LOCK:
        for cluster in candidates:
            if cluster.id in _IN_FLIGHT_CLUSTER_IDS:
                continue
            _IN_FLIGHT_CLUSTER_IDS.add(cluster.id)
            reserved.append(cluster)
            if len(reserved) == limit:
                break
    return reserved


def _release_candidate(cluster_id: uuid.UUID) -> None:
    with _IN_FLIGHT_CLUSTER_IDS_LOCK:
        _IN_FLIGHT_CLUSTER_IDS.discard(cluster_id)


def _build_source_refs(cluster: NewsCluster) -> list[rewrite_pb2.SourceRef]:
    return [
        rewrite_pb2.SourceRef(
            raw_item_id=str(item.id),
            title=item.title,
            url=item.url,
            tier=item.source.tier,
            language=item.language,
            excerpt_or_full_text=item.body or item.title,
            is_full_text=item.is_full_text,
            source_name=item.source.name,
        )
        for item in cluster.raw_items
    ]


def _persist_cluster_context(db: Session, cluster_id, response_ctx) -> None:
    ctx = db.get(ClusterContext, cluster_id)
    if ctx is None:
        ctx = ClusterContext(cluster_id=cluster_id)
        db.add(ctx)
    ctx.facts = [{"kind": f.kind, "text": f.text} for f in response_ctx.facts]
    ctx.press_release = response_ctx.press_release
    ctx.regulated = response_ctx.regulated
    ctx.market_sensitive = response_ctx.market_sensitive
    ctx.fact_conflict = response_ctx.fact_conflict
    ctx.fact_conflict_note = response_ctx.fact_conflict_note or None
    ctx.political_core = response_ctx.political_core
    ctx.promotional_or_partner = response_ctx.promotional_or_partner
    ctx.exclusion_evidence = response_ctx.exclusion_evidence or None


def _usage_from_proto(usage) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _persist_draft(
    db: Session,
    cluster: NewsCluster,
    draft_content,
    *,
    prompt_version_id: str,
    trace_id: str,
    rewrite_usage,
    translate_usage,
    enrich_usage=None,
) -> Draft:
    # content_generated_at must be set before flush: column is NOT NULL and
    # prod DB historically lacked server_default (SA still omitted it via
    # mapped server_default=func.now()). apply_rewrite_content overwrites it.
    draft = Draft(
        cluster_id=cluster.id,
        trace_id=trace_id,
        content_generated_at=datetime.now(UTC),
    )
    db.add(draft)
    db.flush()
    tokens = _usage_from_proto(enrich_usage) + _usage_from_proto(rewrite_usage)
    apply_rewrite_content(
        db,
        draft,
        draft_content,
        prompt_version_id=prompt_version_id or None,
        trace_id=trace_id,
        rewrite_key_alias=rewrite_usage.key_alias or None,
        rewrite_model=rewrite_usage.model or None,
        translate_key_alias=translate_usage.key_alias or None,
        translate_model=translate_usage.model or None,
        llm_prompt_tokens=tokens.prompt_tokens,
        llm_completion_tokens=tokens.completion_tokens,
        llm_total_tokens=tokens.total_tokens,
        revision_kind=DraftRevisionKind.AI_GENERATED,
        bump_version=False,
        editorial_topic=cluster.topic,
    )
    if tokens.total_tokens or tokens.prompt_tokens or tokens.completion_tokens:
        record_token_usage(db, tokens, calls=1 if enrich_usage is None else 2)
    return draft


def run_dispatch_cycle(db: Session, *, settings: WorkerSettings | None = None) -> dict:
    """Phase 4 closes the loop: priority-selected clusters (Phase 3, ТЗ
    §4.3) get Enriched then Rewritten via scribely-rewrite over gRPC, and
    the result becomes a real Draft + its first DraftRevision (ТЗ
    §4.4-§4.13, §4.20). A dead-lettered cluster (AllKeysExhaustedError or
    MAX_ATTEMPTS exhausted server-side) surfaces here as a gRPC error. A
    second failed attempt defers that cluster for six hours so one bad item
    cannot consume every minute of dispatch capacity."""
    settings = settings or WorkerSettings()
    batch_size = max(1, int(get_setting(db, BATCH_SIZE_SETTING_KEY, DISPATCH_BATCH_SIZE)))
    daily_limit = effective_daily_limit(db)
    remaining_today = max(0, daily_limit - _drafts_created_today(db))
    target_per_hour = max(
        1, int(get_setting(db, TARGET_PER_HOUR_SETTING_KEY, DEFAULT_TARGET_PER_HOUR))
    )
    remaining_this_hour = max(0, target_per_hour - _drafts_created_this_hour(db))
    # Manual admin bursts must not be throttled by the hourly target.
    burst_left = manual_burst_remaining(db)
    if burst_left > 0:
        remaining_this_hour = max(remaining_this_hour, burst_left)
    if remaining_today == 0 or remaining_this_hour == 0:
        record_dispatch_cycle_result(db, dispatched=0, failed=0)
        return {"dispatched": 0, "failed": 0}
    drafted_ids = _already_drafted_cluster_ids(db)
    excluded_ids = (
        drafted_ids
        | _active_quarantined_cluster_ids(db)
        | _deferred_cluster_ids(db, now=datetime.now(UTC))
    )
    candidates = select_top_clusters(
        db,
        # Request enough rows to find a non-reserved candidate when the
        # other two dispatch jobs are already working on the top priority.
        limit=min(remaining_today, remaining_this_hour),
        exclude_cluster_ids=excluded_ids,
    )
    candidates = _reserve_candidates(
        candidates,
        limit=min(batch_size, remaining_today, remaining_this_hour),
    )
    if not candidates:
        record_dispatch_cycle_result(db, dispatched=0, failed=0)
        return {"dispatched": 0, "failed": 0}

    channel = build_rewrite_channel(settings)
    stub = rewrite_stub(channel)
    dispatched, failed = 0, 0
    last_error_message: str | None = None
    try:
        for cluster in candidates:
            set_trace_id(new_trace_id())
            trace_id = get_trace_id()
            sources = _build_source_refs(cluster)
            try:
                enrich_resp = stub.EnrichCluster(
                    rewrite_pb2.EnrichClusterRequest(
                        cluster_id=str(cluster.id), sources=sources, trace_id=trace_id
                    )
                )
                _persist_cluster_context(db, cluster.id, enrich_resp.context)
                if enrich_resp.context.political_core or enrich_resp.context.promotional_or_partner:
                    reason = (
                        QuarantineReason.POLITICAL_CORE
                        if enrich_resp.context.political_core
                        else QuarantineReason.PROMOTIONAL_OR_PARTNER
                    )
                    _quarantine_cluster(
                        db,
                        cluster.id,
                        reason,
                        enrich_resp.context.exclusion_evidence
                        or "Автоматическая классификация источника",
                    )
                    db.commit()
                    logger.info("cluster %s quarantined: %s", cluster.id, reason)
                    continue
                db.commit()

                rewrite_resp = stub.RewriteCluster(
                    rewrite_pb2.RewriteClusterRequest(
                        context=enrich_resp.context, trace_id=trace_id
                    )
                )
                _persist_draft(
                    db,
                    cluster,
                    rewrite_resp.draft,
                    prompt_version_id=rewrite_resp.prompt_version_id,
                    trace_id=trace_id,
                    rewrite_usage=rewrite_resp.rewrite_usage,
                    translate_usage=rewrite_resp.translate_usage,
                    enrich_usage=getattr(enrich_resp, "llm_usage", None),
                )
                db.commit()
                dispatched += 1
                record_manual_burst_draft(db)
                db.commit()
            except grpc.RpcError as exc:
                db.rollback()
                details = exc.details() or str(exc)
                last_error_message = details
                logger.warning(
                    "dispatch failed for cluster %s: %s %s",
                    cluster.id,
                    exc.code(),
                    details,
                )
                if "quality gate failed:" in details:
                    _quarantine_cluster(
                        db,
                        cluster.id,
                        QuarantineReason.FACTUAL_VERIFICATION_FAILED,
                        details,
                    )
                    db.commit()
                _record_failed_cluster(db, cluster.id, details)
                failed += 1
            finally:
                _release_candidate(cluster.id)
    finally:
        # A defensive release for exceptions outside a single RPC handler.
        for cluster in candidates:
            _release_candidate(cluster.id)
        channel.close()

    record_dispatch_cycle_result(
        db,
        dispatched=dispatched,
        failed=failed,
        last_error_message=last_error_message,
    )
    return {"dispatched": dispatched, "failed": failed}
