"""Tag/Category resolution against theunum.io (ТЗ §4.19).

theunum.io's Tag/Category API isn't available yet (user decision,
CLAUDE.md "Открыто" — mock-fallback per ТЗ §8.2: "тот же контракт,
локальный стаб"). `resolve_tags_and_category` is the contract a future
real HTTP client would implement instead of this module — dedupe by
slug against the read-only cache, create if missing, return real ids.
Swapping the mock for a real theunum.io client later is a one-function
change; callers (api_app/publish/service.py) don't need to change.
"""

from __future__ import annotations

from db.enums import TagCategoryKind
from db.models import Draft, TagCategoryCache
from sqlalchemy import select
from sqlalchemy.orm import Session


def _resolve_one(db: Session, *, kind: TagCategoryKind, slug: str, name: str) -> str:
    existing = db.scalar(
        select(TagCategoryCache).where(TagCategoryCache.kind == kind, TagCategoryCache.slug == slug)
    )
    if existing is not None:
        return existing.id

    new_id = f"mock-{kind.value}-{slug}"
    db.add(TagCategoryCache(id=new_id, kind=kind, slug=slug, name_en=name))
    db.flush()
    return new_id


def resolve_tags_and_category(db: Session, draft: Draft) -> tuple[str | None, list[str]]:
    """CreateTag/EnsureCategory for every unresolved candidate on
    `draft` (ТЗ §4.19 Approve flow). Already-resolved ids (LLM picked
    an existing tag before Approve) pass through unchanged."""
    category_id = draft.category_id
    if category_id is None and draft.pending_category_slug:
        category_id = _resolve_one(
            db,
            kind=TagCategoryKind.CATEGORY,
            slug=draft.pending_category_slug,
            name=draft.pending_category_slug,
        )

    tag_ids = list(draft.tag_ids)
    for candidate in draft.pending_tags:
        tag_id = _resolve_one(
            db,
            kind=TagCategoryKind.TAG,
            slug=candidate["slug"],
            name=candidate.get("name", candidate["slug"]),
        )
        if tag_id not in tag_ids:
            tag_ids.append(tag_id)

    return category_id, tag_ids
