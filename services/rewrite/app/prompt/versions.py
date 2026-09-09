from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from sqlalchemy import select
from sqlalchemy.orm import Session

PROMPT_V6_NOTES = (
    "v6 — source-grounded neutral rewrite, no unsolicited attribution, "
    "RU dash and anglicism rules; seeded 2026-09-09"
)
# One-shot auto-upgrade prefixes for factory seeds only.
_FACTORY_UPGRADE_PREFIXES = (
    "v1 — bootstrapped",
    "v2 — RU-first SEO",
    "v3 — RU-first SEO",
    "v4 — factual fidelity",
    "v5 — editorial quality",
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

    Fresh DB: bootstrap v6 from style_guide.
    Factory v1–v5 seeds: one-shot retire + create v6 so prod picks up
    source-grounding and neutral-style changes without a manual Admin click.
    Custom Admin prompts (other notes) are left untouched.
    """
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is None:
        return _create_active(db, notes=PROMPT_V6_NOTES)

    notes = active.notes or ""
    if _should_auto_upgrade(notes):
        for row in db.scalars(
            select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
        ):
            row.status = PromptVersionStatus.RETIRED
        db.flush()
        return _create_active(db, notes=PROMPT_V6_NOTES)

    return active
