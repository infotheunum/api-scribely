from __future__ import annotations

import logging

import grpc
from common.grpc_client import build_rewrite_channel, rewrite_stub
from common.tracing import get_trace_id, new_trace_id, set_trace_id
from db.enums import DraftRevisionKind, DraftStatus
from db.models import ClusterContext, Draft, DraftRevision, NewsCluster
from scribely.rewrite.v1 import rewrite_pb2
from sqlalchemy import select
from sqlalchemy.orm import Session
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
DISPATCH_BATCH_SIZE = 3


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


def _persist_draft(
    db: Session,
    cluster: NewsCluster,
    draft_content,
    *,
    prompt_version_id: str,
    trace_id: str,
    rewrite_usage,
    translate_usage,
) -> Draft:
    draft = Draft(
        cluster_id=cluster.id,
        title_en=draft_content.title_en,
        body_en=draft_content.body_en,
        title_ru=draft_content.title_ru,
        body_ru=draft_content.body_ru,
        title_en_variants=list(draft_content.title_en_variants),
        title_ru_variants=list(draft_content.title_ru_variants),
        attribution_urls=list(draft_content.attribution_urls),
        sponsor_flag=draft_content.sponsor_flag,
        press_release_flag=draft_content.press_release_flag,
        disclaimer_flag=draft_content.disclaimer_flag,
        fact_conflict=draft_content.fact_conflict,
        rewrite_llm_key_alias=rewrite_usage.key_alias or None,
        rewrite_llm_model=rewrite_usage.model or None,
        translate_llm_key_alias=translate_usage.key_alias or None,
        translate_llm_model=translate_usage.model or None,
        status=DraftStatus.READY_FOR_REVIEW,
        trace_id=trace_id,
        prompt_version_id=prompt_version_id or None,
        seo_title_en=draft_content.seo_en.seo_title,
        seo_description_en=draft_content.seo_en.seo_description,
        slug_en=draft_content.seo_en.slug,
        og_title_en=draft_content.seo_en.og_title,
        og_description_en=draft_content.seo_en.og_description,
        focus_keyphrase_en=draft_content.seo_en.focus_keyphrase,
        keywords_en=list(draft_content.seo_en.keywords),
        seo_title_ru=draft_content.seo_ru.seo_title,
        seo_description_ru=draft_content.seo_ru.seo_description,
        slug_ru=draft_content.seo_ru.slug,
        og_title_ru=draft_content.seo_ru.og_title,
        og_description_ru=draft_content.seo_ru.og_description,
        focus_keyphrase_ru=draft_content.seo_ru.focus_keyphrase,
        keywords_ru=list(draft_content.seo_ru.keywords),
        image_brief=draft_content.image_brief.image_brief,
        image_mood=draft_content.image_brief.image_mood,
        image_subjects=list(draft_content.image_brief.image_subjects),
        image_style=draft_content.image_brief.image_style,
        image_do_not=list(draft_content.image_brief.image_do_not),
        image_alt=draft_content.image_brief.image_alt,
        image_caption=draft_content.image_brief.image_caption,
        image_source_suggestion=draft_content.image_brief.image_source_suggestion,
        pending_tags=[{"slug": t.slug, "name": t.name} for t in draft_content.tags],
    )
    db.add(draft)
    db.flush()  # need draft.id for the DraftRevision FK before commit

    db.add(
        DraftRevision(
            draft_id=draft.id,
            kind=DraftRevisionKind.AI_GENERATED,
            title_en=draft_content.title_en,
            body_en=draft_content.body_en,
            title_ru=draft_content.title_ru,
            body_ru=draft_content.body_ru,
            prompt_version_id=prompt_version_id or None,
        )
    )
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
    drafted_ids = _already_drafted_cluster_ids(db)
    candidates = [c for c in select_top_clusters(db) if c.id not in drafted_ids][
        :DISPATCH_BATCH_SIZE
    ]
    if not candidates:
        return {"dispatched": 0, "failed": 0}

    channel = build_rewrite_channel(settings)
    stub = rewrite_stub(channel)
    dispatched, failed = 0, 0
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
                )
                db.commit()
                dispatched += 1
            except grpc.RpcError as exc:
                db.rollback()
                logger.warning(
                    "dispatch failed for cluster %s: %s %s",
                    cluster.id,
                    exc.code(),
                    exc.details(),
                )
                failed += 1
    finally:
        channel.close()

    return {"dispatched": dispatched, "failed": failed}
