from __future__ import annotations

import uuid
from datetime import datetime

from api_app.auth.dependencies import require_role
from api_app.db import get_db
from api_app.publish.service import approve_and_publish, submit_edit_feedback
from common.rewrite_body_format import normalize_body_paragraphs
from common.tracing import get_trace_id
from db.enums import DraftStatus, RejectReason
from db.models import AuditLog, Draft, NewsCluster, RawItem, User
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

router = APIRouter(prefix="/drafts", tags=["drafts"])

# What "the queue" means by default — everything else (DRAFTING, PUBLISHED,
# REJECTED, ARCHIVED, SNOOZED) needs an explicit ?status= filter to view.
DEFAULT_QUEUE_STATUSES = [DraftStatus.READY_FOR_REVIEW, DraftStatus.NEEDS_FIX]


def _audit(db: Session, user: User, *, action: str, draft_id: uuid.UUID, details: dict) -> None:
    db.add(
        AuditLog(
            actor_id=user.id,
            action=action,
            entity_type="Draft",
            entity_id=str(draft_id),
            details=details,
            trace_id=get_trace_id(),
        )
    )


def _needs_attention(draft: Draft) -> bool:
    """ТЗ §6.3 Фаза 6: очередь отсортирована так, чтобы черновики с
    compliance-флагами/fact_conflict/similarity-gate поднимались наверх."""
    return bool(
        draft.status == DraftStatus.NEEDS_FIX
        or draft.sensitive_hold
        or draft.fact_conflict
        or draft.sponsor_flag
        or draft.press_release_flag
    )


class DraftSummary(BaseModel):
    id: str
    status: str
    title_en: str
    title_ru: str
    topic: str | None
    sponsor_flag: bool
    press_release_flag: bool
    disclaimer_flag: bool
    fact_conflict: bool
    sensitive_hold: bool
    similarity_score: float | None
    needs_attention: bool
    assignee_user_id: str | None
    created_at: datetime
    updated_at: datetime
    content_generated_at: datetime
    version: int

    @classmethod
    def from_model(cls, draft: Draft) -> DraftSummary:
        return cls(
            id=str(draft.id),
            status=draft.status,
            title_en=draft.title_en,
            title_ru=draft.title_ru,
            topic=draft.cluster.topic if draft.cluster else None,
            sponsor_flag=draft.sponsor_flag,
            press_release_flag=draft.press_release_flag,
            disclaimer_flag=draft.disclaimer_flag,
            fact_conflict=draft.fact_conflict,
            sensitive_hold=draft.sensitive_hold,
            similarity_score=draft.similarity_score,
            needs_attention=_needs_attention(draft),
            assignee_user_id=str(draft.assignee_user_id) if draft.assignee_user_id else None,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            content_generated_at=draft.content_generated_at,
            version=draft.version,
        )


class SourceRefOut(BaseModel):
    title: str
    url: str
    language: str
    source_name: str


class DraftDetail(DraftSummary):
    body_en: str
    body_ru: str
    title_en_variants: list[str]
    title_ru_variants: list[str]
    attribution_urls: list[str]
    compliance_notes: list[str]
    seo_title_en: str | None
    seo_description_en: str | None
    slug_en: str | None
    og_title_en: str | None
    og_description_en: str | None
    focus_keyphrase_en: str | None
    keywords_en: list[str]
    seo_title_ru: str | None
    seo_description_ru: str | None
    slug_ru: str | None
    og_title_ru: str | None
    og_description_ru: str | None
    focus_keyphrase_ru: str | None
    keywords_ru: list[str]
    image_brief: str | None
    image_mood: str | None
    image_subjects: list[str]
    image_style: str | None
    image_do_not: list[str]
    image_alt: str | None
    image_caption: str | None
    image_source_suggestion: str | None
    image_license_confirmed: bool
    category_id: str | None
    tag_ids: list[str]
    pending_category_slug: str | None
    pending_tags: list
    handoff_note: str | None
    rewrite_llm_model: str | None
    sources: list[SourceRefOut]

    @classmethod
    def from_model(cls, draft: Draft) -> DraftDetail:
        summary = DraftSummary.from_model(draft)
        sources = [
            SourceRefOut(
                title=item.title,
                url=item.url,
                language=item.language,
                source_name=item.source.name if item.source else "",
            )
            for item in (draft.cluster.raw_items if draft.cluster else [])
        ]
        return cls(
            **summary.model_dump(),
            body_en=normalize_body_paragraphs(draft.body_en or ""),
            body_ru=normalize_body_paragraphs(draft.body_ru or ""),
            title_en_variants=draft.title_en_variants,
            title_ru_variants=draft.title_ru_variants,
            attribution_urls=draft.attribution_urls,
            compliance_notes=draft.compliance_notes,
            seo_title_en=draft.seo_title_en,
            seo_description_en=draft.seo_description_en,
            slug_en=draft.slug_en,
            og_title_en=draft.og_title_en,
            og_description_en=draft.og_description_en,
            focus_keyphrase_en=draft.focus_keyphrase_en,
            keywords_en=draft.keywords_en,
            seo_title_ru=draft.seo_title_ru,
            seo_description_ru=draft.seo_description_ru,
            slug_ru=draft.slug_ru,
            og_title_ru=draft.og_title_ru,
            og_description_ru=draft.og_description_ru,
            focus_keyphrase_ru=draft.focus_keyphrase_ru,
            keywords_ru=draft.keywords_ru,
            image_brief=draft.image_brief,
            image_mood=draft.image_mood,
            image_subjects=draft.image_subjects,
            image_style=draft.image_style,
            image_do_not=draft.image_do_not,
            image_alt=draft.image_alt,
            image_caption=draft.image_caption,
            image_source_suggestion=draft.image_source_suggestion,
            image_license_confirmed=draft.image_license_confirmed,
            category_id=draft.category_id,
            tag_ids=draft.tag_ids,
            pending_category_slug=draft.pending_category_slug,
            pending_tags=draft.pending_tags,
            handoff_note=draft.handoff_note,
            rewrite_llm_model=draft.rewrite_llm_model,
            sources=sources,
        )


class DraftPatch(BaseModel):
    """Partial edit — only editable content fields, never status/flags/
    lock bookkeeping. `version` is required (ТЗ §4.15 optimistic
    concurrency) — the PATCH is rejected with 409 if it's stale."""

    version: int
    title_en: str | None = None
    body_en: str | None = None
    title_ru: str | None = None
    body_ru: str | None = None
    seo_title_en: str | None = None
    seo_description_en: str | None = None
    slug_en: str | None = None
    og_title_en: str | None = None
    og_description_en: str | None = None
    focus_keyphrase_en: str | None = None
    keywords_en: list[str] | None = None
    seo_title_ru: str | None = None
    seo_description_ru: str | None = None
    slug_ru: str | None = None
    og_title_ru: str | None = None
    og_description_ru: str | None = None
    focus_keyphrase_ru: str | None = None
    keywords_ru: list[str] | None = None
    image_brief: str | None = None
    image_mood: str | None = None
    image_subjects: list[str] | None = None
    image_style: str | None = None
    image_do_not: list[str] | None = None
    image_alt: str | None = None
    image_caption: str | None = None
    image_source_suggestion: str | None = None
    image_license_confirmed: bool | None = None
    pending_tags: list | None = None


class ActionReasonBody(BaseModel):
    reason: RejectReason
    note: str | None = None


class SnoozeBody(BaseModel):
    note: str | None = None


def _get_draft_or_404(db: Session, draft_id: uuid.UUID) -> Draft:
    load_sources = (
        joinedload(Draft.cluster).joinedload(NewsCluster.raw_items).joinedload(RawItem.source)
    )
    draft = db.get(Draft, draft_id, options=[load_sources])
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    return draft


@router.get("", response_model=list[DraftSummary])
def list_drafts(
    status_filter: list[str] | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("rewriter", "admin")),
) -> list[DraftSummary]:
    statuses = status_filter or [s.value for s in DEFAULT_QUEUE_STATUSES]
    drafts = db.scalars(
        select(Draft)
        .where(Draft.status.in_(statuses))
        .options(joinedload(Draft.cluster))
        .order_by(Draft.created_at.asc())
    ).all()
    summaries = [DraftSummary.from_model(d) for d in drafts]
    # needs_attention first, oldest-first within each group — a noisy
    # source's backlog still can't bury a flagged draft behind it.
    summaries.sort(key=lambda s: (not s.needs_attention, s.created_at))
    return summaries


@router.get("/{draft_id}", response_model=DraftDetail)
def get_draft(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    return DraftDetail.from_model(_get_draft_or_404(db, draft_id))


@router.patch("/{draft_id}", response_model=DraftDetail)
def patch_draft(
    draft_id: uuid.UUID,
    body: DraftPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    draft = _get_draft_or_404(db, draft_id)
    if draft.version != body.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"stale version: draft is at {draft.version}, you edited {body.version}",
        )
    changes = body.model_dump(exclude={"version"}, exclude_unset=True)
    for field, value in changes.items():
        setattr(draft, field, value)
    draft.version += 1
    _audit(db, user, action="edit", draft_id=draft.id, details={"fields": list(changes)})
    db.flush()
    db.refresh(draft)
    return DraftDetail.from_model(draft)


@router.post("/{draft_id}/publish", response_model=DraftDetail)
def publish_draft(
    request: Request,
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    """Publishes both language versions at once (ТЗ §4.8) — one Draft
    row, one status. The article itself stays no-op (Publish Adapter,
    ТЗ §1.1/§4.8) — the one real exception is tag/category ids, resolved
    for real against theunum.io (mock-backed for now, ТЗ §4.19) before
    the status flip, never left as local-only candidates."""
    draft = _get_draft_or_404(db, draft_id)
    if not draft.image_license_confirmed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "cover image license must be confirmed before Publish"
        )
    category_id, tag_ids = approve_and_publish(db, draft, user)
    draft.status = DraftStatus.PUBLISHED
    _audit(
        db,
        user,
        action="publish",
        draft_id=draft.id,
        details={"category_id": category_id, "tag_ids": tag_ids},
    )
    db.flush()
    submit_edit_feedback(db, request.app.state.rewrite_channel, draft=draft, author_id=user.id)
    db.refresh(draft)
    return DraftDetail.from_model(draft)


@router.post("/{draft_id}/reject", response_model=DraftDetail)
def reject_draft(
    request: Request,
    draft_id: uuid.UUID,
    body: ActionReasonBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    draft = _get_draft_or_404(db, draft_id)
    draft.status = DraftStatus.REJECTED
    _audit(
        db,
        user,
        action="reject",
        draft_id=draft.id,
        details={"reason": body.reason.value, "note": body.note},
    )
    db.flush()
    submit_edit_feedback(db, request.app.state.rewrite_channel, draft=draft, author_id=user.id)
    db.refresh(draft)
    return DraftDetail.from_model(draft)


@router.post("/{draft_id}/needs-fix", response_model=DraftDetail)
def needs_fix_draft(
    draft_id: uuid.UUID,
    body: ActionReasonBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    draft = _get_draft_or_404(db, draft_id)
    draft.status = DraftStatus.NEEDS_FIX
    _audit(
        db,
        user,
        action="needs_fix",
        draft_id=draft.id,
        details={"reason": body.reason.value, "note": body.note},
    )
    db.flush()
    db.refresh(draft)
    return DraftDetail.from_model(draft)


@router.post("/{draft_id}/snooze", response_model=DraftDetail)
def snooze_draft(
    draft_id: uuid.UUID,
    body: SnoozeBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    draft = _get_draft_or_404(db, draft_id)
    draft.status = DraftStatus.SNOOZED
    draft.handoff_note = body.note
    _audit(db, user, action="snooze", draft_id=draft.id, details={"note": body.note})
    db.flush()
    db.refresh(draft)
    return DraftDetail.from_model(draft)


@router.post("/{draft_id}/unsnooze", response_model=DraftDetail)
def unsnooze_draft(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> DraftDetail:
    draft = _get_draft_or_404(db, draft_id)
    draft.status = DraftStatus.READY_FOR_REVIEW
    _audit(db, user, action="unsnooze", draft_id=draft.id, details={})
    db.flush()
    db.refresh(draft)
    return DraftDetail.from_model(draft)
