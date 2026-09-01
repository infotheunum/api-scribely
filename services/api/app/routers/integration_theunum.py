from __future__ import annotations

import uuid
from datetime import datetime

from api_app.auth.integration import require_integration_token_dep
from api_app.db import get_db
from api_app.integrations.freshness import FreshnessPreset, resolve_content_generated_since
from api_app.integrations.pipeline_status import build_list_meta, build_pipeline_status
from common.integration_export_settings import merge_export_freshness_query
from api_app.routers.drafts import DEFAULT_QUEUE_STATUSES, DraftDetail
from common.rewrite_body_format import body_to_html
from common.tracing import get_trace_id
from db.models import AuditLog, Draft, DraftExportLog, NewsCluster, RawItem
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

router = APIRouter(
    prefix="/integrations/theunum/v1",
    tags=["integrations-theunum"],
    dependencies=[Depends(require_integration_token_dep)],
)

DEFAULT_EXPORT_STATUSES = [s.value for s in DEFAULT_QUEUE_STATUSES]


class IntegrationDraftExport(DraftDetail):
    consumed_at: datetime | None = None
    body_en_html: str = ""
    body_ru_html: str = ""


def _to_integration_export(draft: Draft, export_log: DraftExportLog | None) -> IntegrationDraftExport:
    detail = DraftDetail.from_model(draft)
    return IntegrationDraftExport(
        **detail.model_dump(),
        body_en_html=body_to_html(detail.body_en),
        body_ru_html=body_to_html(detail.body_ru),
        consumed_at=export_log.consumed_at if export_log else None,
    )


class DraftListResponse(BaseModel):
    items: list[IntegrationDraftExport]
    next_cursor: str | None
    has_more: bool
    meta: dict


class MarkConsumedItem(BaseModel):
    draft_id: uuid.UUID
    theunum_reference_id: str | None = None


class MarkConsumedBody(BaseModel):
    theunum_reference_id: str | None = None


class MarkConsumedBatch(BaseModel):
    items: list[MarkConsumedItem] = Field(default_factory=list)


class MarkConsumedResponse(BaseModel):
    marked: int
    draft_ids: list[str]


def _load_draft(db: Session, draft_id: uuid.UUID) -> Draft:
    load_sources = (
        joinedload(Draft.cluster).joinedload(NewsCluster.raw_items).joinedload(RawItem.source)
    )
    draft = db.get(
        Draft,
        draft_id,
        options=[load_sources, joinedload(Draft.export_log)],
    )
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    return draft


def _drafts_query(
    db: Session,
    *,
    statuses: list[str],
    consumed: bool,
    since: datetime | None,
    generated_since: datetime | None,
    cursor: uuid.UUID | None,
):
    stmt = (
        select(Draft)
        .outerjoin(DraftExportLog, DraftExportLog.draft_id == Draft.id)
        .options(
            joinedload(Draft.cluster).joinedload(NewsCluster.raw_items).joinedload(RawItem.source),
            joinedload(Draft.export_log),
        )
        .where(Draft.status.in_(statuses))
    )
    if consumed:
        stmt = stmt.where(DraftExportLog.draft_id.is_not(None))
    else:
        stmt = stmt.where(DraftExportLog.draft_id.is_(None))
    if since is not None:
        stmt = stmt.where(Draft.updated_at >= since)
    if generated_since is not None:
        stmt = stmt.where(Draft.content_generated_at >= generated_since)
    if cursor is not None:
        cursor_draft = db.get(Draft, cursor)
        if cursor_draft is not None:
            stmt = stmt.where(
                (Draft.created_at > cursor_draft.created_at)
                | ((Draft.created_at == cursor_draft.created_at) & (Draft.id > cursor_draft.id))
            )
    return stmt.order_by(Draft.created_at.asc(), Draft.id.asc())


def _list_export_drafts_impl(
    request: Request,
    db: Session,
    *,
    statuses: list[str],
    consumed: bool,
    since: datetime | None,
    generated_since: datetime | None,
    freshness: FreshnessPreset | None,
    max_age_hours: int | None,
    cursor: uuid.UUID | None,
    limit: int,
) -> DraftListResponse:
    generated_since, freshness, max_age_hours, freshness_source = merge_export_freshness_query(
        db,
        generated_since=generated_since,
        freshness=freshness,
        max_age_hours=max_age_hours,
    )
    try:
        effective_generated_since = resolve_content_generated_since(
            generated_since=generated_since,
            freshness=freshness,
            max_age_hours=max_age_hours,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    stmt = _drafts_query(
        db,
        statuses=statuses,
        consumed=consumed,
        since=since,
        generated_since=effective_generated_since,
        cursor=cursor,
    )
    drafts = db.scalars(stmt.limit(limit + 1)).unique().all()
    has_more = len(drafts) > limit
    page = drafts[:limit]
    next_cursor = str(page[-1].id) if has_more and page else None

    items = [_to_integration_export(draft, draft.export_log if draft.export_log else None) for draft in page]

    channel = getattr(request.app.state, "rewrite_channel", None)
    meta = build_list_meta(db, rewrite_channel=channel, item_count=len(items))
    if effective_generated_since is not None:
        meta["content_generated_since"] = effective_generated_since.isoformat()
    if freshness is not None:
        meta["freshness"] = freshness
    if max_age_hours is not None:
        meta["max_age_hours"] = max_age_hours
    meta["freshness_source"] = freshness_source
    return DraftListResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        meta=meta,
    )


@router.get("/status")
def integration_status(request: Request, db: Session = Depends(get_db)) -> dict:
    channel = getattr(request.app.state, "rewrite_channel", None)
    return build_pipeline_status(db, rewrite_channel=channel)


@router.get("/drafts", response_model=DraftListResponse)
def list_export_drafts(
    request: Request,
    db: Session = Depends(get_db),
    status_filter: list[str] | None = Query(None, alias="status"),
    consumed: bool = Query(False),
    since: datetime | None = Query(None),
    generated_since: datetime | None = Query(
        None,
        description="Only drafts whose AI rewrite/regen ran at or after this time (ISO8601)",
    ),
    freshness: FreshnessPreset | None = Query(
        None,
        description="Preset freshness filter on content_generated_at: today (UTC midnight) or 48h",
    ),
    max_age_hours: int | None = Query(
        None,
        ge=1,
        le=168,
        description="Only drafts generated within the last N hours (alternative to freshness)",
    ),
    cursor: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> DraftListResponse:
    statuses = status_filter or DEFAULT_EXPORT_STATUSES
    return _list_export_drafts_impl(
        request,
        db,
        statuses=statuses,
        consumed=consumed,
        since=since,
        generated_since=generated_since,
        freshness=freshness,
        max_age_hours=max_age_hours,
        cursor=cursor,
        limit=limit,
    )


@router.get("/drafts/today", response_model=DraftListResponse)
def list_export_drafts_today(
    request: Request,
    db: Session = Depends(get_db),
    status_filter: list[str] | None = Query(None, alias="status"),
    consumed: bool = Query(False),
    cursor: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
) -> DraftListResponse:
    """Shortcut: unconsumed queue drafts with content_generated_at >= UTC midnight today."""
    statuses = status_filter or DEFAULT_EXPORT_STATUSES
    return _list_export_drafts_impl(
        request,
        db,
        statuses=statuses,
        consumed=consumed,
        since=None,
        generated_since=None,
        freshness="today",
        max_age_hours=None,
        cursor=cursor,
        limit=limit,
    )


@router.get("/drafts/{draft_id}", response_model=IntegrationDraftExport)
def get_export_draft(draft_id: uuid.UUID, db: Session = Depends(get_db)) -> IntegrationDraftExport:
    draft = _load_draft(db, draft_id)
    export_log = db.get(DraftExportLog, draft_id)
    return _to_integration_export(draft, export_log)


def _mark_one(db: Session, item: MarkConsumedItem) -> uuid.UUID | None:
    draft = db.get(Draft, item.draft_id)
    if draft is None:
        return None
    existing = db.get(DraftExportLog, item.draft_id)
    if existing is None:
        db.add(
            DraftExportLog(
                draft_id=item.draft_id,
                theunum_reference_id=item.theunum_reference_id,
                trace_id=draft.trace_id,
            )
        )
        db.add(
            AuditLog(
                action="theunum_consumed",
                entity_type="Draft",
                entity_id=str(item.draft_id),
                details={
                    "theunum_reference_id": item.theunum_reference_id,
                    "source": "integration_api",
                },
                trace_id=get_trace_id(),
            )
        )
    elif item.theunum_reference_id and not existing.theunum_reference_id:
        existing.theunum_reference_id = item.theunum_reference_id
    return item.draft_id


@router.post("/drafts/{draft_id}/mark-consumed", response_model=MarkConsumedResponse)
def mark_consumed_one(
    draft_id: uuid.UUID,
    body: MarkConsumedBody = Body(default_factory=MarkConsumedBody),
    db: Session = Depends(get_db),
) -> MarkConsumedResponse:
    ref = body.theunum_reference_id
    marked_id = _mark_one(db, MarkConsumedItem(draft_id=draft_id, theunum_reference_id=ref))
    if marked_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    db.commit()
    return MarkConsumedResponse(marked=1, draft_ids=[str(marked_id)])


@router.post("/drafts/mark-consumed", response_model=MarkConsumedResponse)
def mark_consumed_batch(body: MarkConsumedBatch, db: Session = Depends(get_db)) -> MarkConsumedResponse:
    if not body.items:
        return MarkConsumedResponse(marked=0, draft_ids=[])
    marked_ids: list[str] = []
    for item in body.items:
        draft_id = _mark_one(db, item)
        if draft_id is not None:
            marked_ids.append(str(draft_id))
    db.commit()
    return MarkConsumedResponse(marked=len(marked_ids), draft_ids=marked_ids)
