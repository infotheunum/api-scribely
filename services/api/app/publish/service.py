"""Approve/Publish orchestration (ТЗ §4.8, §4.13, §4.14, §4.19, Фаза 7).

Publish Adapter (the article actually appearing on theunum.io) stays
no-op in MVP, as locked in from Фаза 0 — this module only covers what
ТЗ §4.19 calls out as the one real exception: tag/category ids are
resolved for real (via [[tagsync.client]], mock-backed for now) before
the status flip, never left as local-only candidates.
"""

from __future__ import annotations

import logging

import grpc
from api_app.tagsync.client import resolve_tags_and_category
from common.grpc_client import rewrite_stub
from common.tracing import get_trace_id
from db.enums import DraftRevisionKind
from db.models import Draft, DraftRevision, PublishRecord, User
from scribely.rewrite.v1 import rewrite_pb2
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def approve_and_publish(db: Session, draft: Draft, user: User) -> tuple[str | None, list[str]]:
    """Resolves tags/category and records the Publish paper trail —
    everything except the status flip and AuditLog write, which stay in
    the route next to the image-license gate (drafts.py)."""
    category_id, tag_ids = resolve_tags_and_category(db, draft)
    draft.category_id = category_id
    draft.tag_ids = tag_ids

    db.add(
        PublishRecord(
            draft_id=draft.id,
            published_by=user.id,
            category_id=category_id,
            tag_ids=tag_ids,
            trace_id=get_trace_id(),
        )
    )
    db.add(
        DraftRevision(
            draft_id=draft.id,
            kind=DraftRevisionKind.HUMAN_FINAL,
            title_en=draft.title_en,
            body_en=draft.body_en,
            title_ru=draft.title_ru,
            body_ru=draft.body_ru,
            author_id=user.id,
            prompt_version_id=draft.prompt_version_id,
        )
    )
    db.flush()
    return category_id, tag_ids


def _ai_generated_text(db: Session, draft: Draft, locale: str) -> str:
    revision = db.scalar(
        select(DraftRevision).where(
            DraftRevision.draft_id == draft.id,
            DraftRevision.kind == DraftRevisionKind.AI_GENERATED,
        )
    )
    if revision is None:
        return ""
    if locale == "en":
        return f"{revision.title_en}\n\n{revision.body_en}"
    return f"{revision.title_ru}\n\n{revision.body_ru}"


def submit_edit_feedback(
    db: Session, channel: grpc.Channel | None, *, draft: Draft, author_id
) -> None:
    """Best-effort — theunum.io's style-vector proxy is a contract/mock
    on rewrite's side (ТЗ §4.14); a transient outage there must never
    block an editor's Publish/Reject action."""
    if channel is None:
        return
    stub = rewrite_stub(channel)
    for locale, human_text in (
        ("en", f"{draft.title_en}\n\n{draft.body_en}"),
        ("ru", f"{draft.title_ru}\n\n{draft.body_ru}"),
    ):
        try:
            stub.SubmitEditFeedback(
                rewrite_pb2.SubmitEditFeedbackRequest(
                    draft_id=str(draft.id),
                    author_id=str(author_id),
                    ai_generated_text=_ai_generated_text(db, draft, locale),
                    human_final_text=human_text,
                    locale=locale,
                    trace_id=get_trace_id(),
                ),
                timeout=5.0,
            )
        except grpc.RpcError as exc:
            logger.warning(
                "SubmitEditFeedback failed (draft=%s locale=%s): %s", draft.id, locale, exc
            )
