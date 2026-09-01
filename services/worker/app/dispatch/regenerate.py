from __future__ import annotations

import logging
import uuid

import grpc
from common.grpc_client import build_rewrite_channel, rewrite_stub
from common.tracing import get_trace_id, new_trace_id, set_trace_id
from db.enums import DraftRevisionKind, DraftStatus
from db.models import Draft, DraftExportLog, NewsCluster, RawItem
from rewrite_app.prompt.style_guide import BODY_MIN_CHARS
from scribely.rewrite.v1 import rewrite_pb2
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from worker_app.compliance.pipeline import _gate_draft
from worker_app.dispatch.draft_apply import apply_rewrite_content
from worker_app.dispatch.pipeline import _build_source_refs, _persist_cluster_context
from worker_app.settings import WorkerSettings

logger = logging.getLogger(__name__)

REGENERATABLE_STATUSES = (DraftStatus.READY_FOR_REVIEW, DraftStatus.NEEDS_FIX)


def select_drafts_for_regeneration(
    db: Session,
    *,
    all_queue: bool,
    limit: int,
    offset: int = 0,
) -> list[Draft]:
    stmt = (
        select(Draft)
        .where(Draft.status.in_(REGENERATABLE_STATUSES))
        .order_by(Draft.created_at)
        .offset(offset)
        .limit(limit)
    )
    if not all_queue:
        stmt = stmt.where(
            or_(
                func.length(Draft.body_en) < BODY_MIN_CHARS,
                func.length(Draft.body_ru) < BODY_MIN_CHARS,
            )
        )
    return list(db.scalars(stmt).all())


def count_drafts_for_regeneration(db: Session, *, all_queue: bool) -> int:
    stmt = select(func.count()).select_from(Draft).where(Draft.status.in_(REGENERATABLE_STATUSES))
    if not all_queue:
        stmt = stmt.where(
            or_(
                func.length(Draft.body_en) < BODY_MIN_CHARS,
                func.length(Draft.body_ru) < BODY_MIN_CHARS,
            )
        )
    return int(db.scalar(stmt) or 0)


def _load_cluster(db: Session, cluster_id: uuid.UUID) -> NewsCluster | None:
    return db.scalar(
        select(NewsCluster)
        .where(NewsCluster.id == cluster_id)
        .options(joinedload(NewsCluster.raw_items).joinedload(RawItem.source))
    )


def regenerate_draft(
    db: Session,
    draft: Draft,
    *,
    settings: WorkerSettings,
    stub,
    clear_export: bool,
) -> None:
    cluster = _load_cluster(db, draft.cluster_id)
    if cluster is None:
        raise RuntimeError(f"cluster {draft.cluster_id} not found for draft {draft.id}")

    set_trace_id(new_trace_id())
    trace_id = get_trace_id()
    sources = _build_source_refs(cluster)

    enrich_resp = stub.EnrichCluster(
        rewrite_pb2.EnrichClusterRequest(cluster_id=str(cluster.id), sources=sources, trace_id=trace_id)
    )
    _persist_cluster_context(db, cluster.id, enrich_resp.context)

    rewrite_resp = stub.RewriteCluster(
        rewrite_pb2.RewriteClusterRequest(context=enrich_resp.context, trace_id=trace_id)
    )
    apply_rewrite_content(
        db,
        draft,
        rewrite_resp.draft,
        prompt_version_id=rewrite_resp.prompt_version_id or None,
        trace_id=trace_id,
        rewrite_key_alias=rewrite_resp.rewrite_usage.key_alias or None,
        rewrite_model=rewrite_resp.rewrite_usage.model or None,
        translate_key_alias=rewrite_resp.translate_usage.key_alias or None,
        translate_model=rewrite_resp.translate_usage.model or None,
        revision_kind=DraftRevisionKind.REGEN,
        bump_version=True,
        editorial_topic=cluster.topic,
    )
    _gate_draft(db, draft)

    if clear_export:
        export_log = db.get(DraftExportLog, draft.id)
        if export_log is not None:
            db.delete(export_log)


def run_regenerate_batch(
    db: Session,
    *,
    settings: WorkerSettings | None = None,
    all_queue: bool = False,
    limit: int = 50,
    offset: int = 0,
    clear_export: bool = True,
) -> dict:
    """Re-run Enrich+Rewrite for existing queue drafts (titles, bodies, SEO)."""
    settings = settings or WorkerSettings()
    drafts = select_drafts_for_regeneration(db, all_queue=all_queue, limit=limit, offset=offset)
    if not drafts:
        return {"selected": 0, "regenerated": 0, "failed": 0, "errors": []}

    channel = build_rewrite_channel(settings)
    stub = rewrite_stub(channel)
    regenerated, failed, errors = 0, 0, []
    try:
        for draft in drafts:
            draft_id = str(draft.id)
            try:
                regenerate_draft(db, draft, settings=settings, stub=stub, clear_export=clear_export)
                db.commit()
                regenerated += 1
                logger.info("regenerated draft %s -> status=%s", draft_id, draft.status)
            except grpc.RpcError as exc:
                db.rollback()
                detail = exc.details() or str(exc)
                failed += 1
                errors.append({"draft_id": draft_id, "error": detail})
                logger.warning("regenerate failed draft %s: %s %s", draft_id, exc.code(), detail)
            except Exception as exc:
                db.rollback()
                failed += 1
                errors.append({"draft_id": draft_id, "error": str(exc)})
                logger.exception("regenerate failed draft %s", draft_id)
    finally:
        channel.close()

    return {
        "selected": len(drafts),
        "regenerated": regenerated,
        "failed": failed,
        "errors": errors,
        "remaining_estimate": max(
            0,
            count_drafts_for_regeneration(db, all_queue=all_queue) - regenerated,
        ),
    }
