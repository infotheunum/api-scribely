from __future__ import annotations

from api_app.auth.dependencies import require_role
from api_app.db import get_db
from common.fulltext import fetch_full_text
from common.tracing import get_trace_id
from db.enums import SourceType
from db.models import RawItem, Source, User
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


class InjectRequest(BaseModel):
    url: HttpUrl
    title: str | None = None


class InjectResponse(BaseModel):
    raw_item_id: str
    created: bool


def _manual_source(db: Session) -> Source:
    source = db.scalar(select(Source).where(Source.type == SourceType.MANUAL))
    if source is None:
        # Seeded by scripts/seed_sources.py — a real deployment that has
        # run migrations but not the seed script hits this once, loudly,
        # instead of silently inventing a pseudo-source row here.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="no MANUAL source configured — run scripts/seed_sources.py",
        )
    return source


@router.post("/inject", response_model=InjectResponse, status_code=status.HTTP_201_CREATED)
def inject_url(
    body: InjectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("rewriter", "admin")),
) -> InjectResponse:
    """Manual "add article by URL" (ТЗ §4.1) — bypasses RSS polling
    entirely, always fetches full text (there's no feed summary to fall
    back to). Idempotent on the URL itself, same as RSS-sourced items are
    on (source_id, guid) — resubmitting the same link is a no-op (ТЗ §4.20)."""
    url = str(body.url)
    source = _manual_source(db)

    existing = db.scalar(
        select(RawItem).where(RawItem.source_id == source.id, RawItem.external_id == url)
    )
    if existing is not None:
        return InjectResponse(raw_item_id=str(existing.id), created=False)

    full_text = fetch_full_text(url)
    raw_item = RawItem(
        source_id=source.id,
        external_id=url,
        url=url,
        title=body.title or url,
        body=full_text,
        is_full_text=full_text is not None,
        language=source.language,
        is_manual_inject=True,
        trace_id=get_trace_id(),
    )
    db.add(raw_item)
    db.flush()
    return InjectResponse(raw_item_id=str(raw_item.id), created=True)
