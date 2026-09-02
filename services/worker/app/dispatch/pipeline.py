from __future__ import annotations

import logging

import grpc
from common.grpc_client import build_rewrite_channel, rewrite_stub
from common.llm_token_totals import record_token_usage
from common.pipeline_telemetry import record_dispatch_cycle_result
from common.token_usage import TokenUsage
from common.tracing import get_trace_id, new_trace_id, set_trace_id
from db.app_settings import get_setting
from db.enums import DraftRevisionKind
from db.models import ClusterContext, Draft, NewsCluster
from scribely.rewrite.v1 import rewrite_pb2
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.dispatch.draft_apply import apply_rewrite_content
from worker_app.filter.queue import select_top_clusters
from worker_app.settings import WorkerSettings

logger = logging.getLogger(__name__)

# Free-tier LLM latency (~45-95s per Enrich+Rewrite round-trip,
# live-observed against real OpenRouter) dwarfs the 60s poll tick that
# this pipeline shares with ingestion/clustering/filtering — a small
# per-tick cap keeps one dispatch burst from starving the rest of the
# tick. There's no daily-published counter yet (queue.py's
# select_top_clusters() docstring already flags this as a follow-up), so
# the 100±10/day KPI (ТЗ §1) is only approximated for now via this cap
# plus the already-has-draft filter below — real throughput tuning is
# deferred past MVP.
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


def _already_drafted_cluster_ids(db: Session) -> set:
    return set(db.scalars(select(Draft.cluster_id)))


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
    draft = Draft(
        cluster_id=cluster.id,
        trace_id=trace_id,
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
    MAX_ATTEMPTS exhausted server-side) surfaces here as a gRPC error —
    this loop just logs it and leaves the cluster undrafted, so it's
    naturally retried next tick since select_top_clusters() only excludes
    clusters that already have a Draft."""
    settings = settings or WorkerSettings()
    batch_size = get_setting(db, BATCH_SIZE_SETTING_KEY, DISPATCH_BATCH_SIZE)
    drafted_ids = _already_drafted_cluster_ids(db)
    candidates = [c for c in select_top_clusters(db) if c.id not in drafted_ids][:batch_size]
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
                failed += 1
    finally:
        channel.close()

    record_dispatch_cycle_result(
        db,
        dispatched=dispatched,
        failed=failed,
        last_error_message=last_error_message,
    )
    return {"dispatched": dispatched, "failed": failed}
