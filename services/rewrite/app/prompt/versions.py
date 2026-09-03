from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from sqlalchemy import select
from sqlalchemy.orm import Session

PROMPT_V3_NOTES = (
    "v3 — RU-first SEO; body hard-min 1700, target 2000–2800, "
    "no hard max (over 3000 accepted); seeded 2026-09-03"
)
# One-shot auto-upgrade prefixes for factory seeds only.
_FACTORY_UPGRADE_PREFIXES = (
    "v1 — bootstrapped",
    "v2 — RU-first SEO",
)


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


def _should_auto_upgrade(notes: str) -> bool:
    return any(notes.startswith(prefix) for prefix in _FACTORY_UPGRADE_PREFIXES)


def get_active_prompt_version(db: Session) -> PromptVersion:
    """Returns the active PromptVersion.

    Fresh DB: bootstrap v3 from style_guide.
    Factory v1/v2 seeds: one-shot retire + create v3 so prod picks up
    body-limit / SEO prompt changes without a manual Admin click.
    Custom Admin prompts (other notes) are left untouched.
    """
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is None:
        return _create_active(db, notes=PROMPT_V3_NOTES)

    notes = active.notes or ""
    if _should_auto_upgrade(notes):
        for row in db.scalars(
            select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
        ):
            row.status = PromptVersionStatus.RETIRED
        db.flush()
        return _create_active(db, notes=PROMPT_V3_NOTES)

    return active
