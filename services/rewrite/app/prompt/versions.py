from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from sqlalchemy import select
from sqlalchemy.orm import Session

PROMPT_V2_NOTES = (
    "v2 — RU-first SEO news, locale-aware, body target 2000–2800 "
    "(hard 1300–3000); seeded 2026-09-03"
)
_FACTORY_V1_PREFIX = "v1 — bootstrapped"


def _create_active(db: Session, *, notes: str) -> PromptVersion:
    version = PromptVersion(
        template=SYSTEM_PROMPT,
        status=PromptVersionStatus.ACTIVE,
        notes=notes,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def get_active_prompt_version(db: Session) -> PromptVersion:
    """Returns the active PromptVersion.

    Fresh DB: bootstrap v2 from style_guide.
    Factory v1 bootstrap (notes start with ``v1 — bootstrapped``): one-shot
    retire + create v2 so prod picks up RU-first SEO prompt without a manual
    Admin click. Custom Admin prompts (other notes) are left untouched —
    activate a new version in Admin if needed.
    """
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is None:
        return _create_active(db, notes=PROMPT_V2_NOTES)

    notes = active.notes or ""
    if notes.startswith(_FACTORY_V1_PREFIX):
        for row in db.scalars(
            select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
        ):
            row.status = PromptVersionStatus.RETIRED
        db.flush()
        return _create_active(db, notes=PROMPT_V2_NOTES)

    return active
