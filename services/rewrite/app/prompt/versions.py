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

    Fresh DB: bootstrap v6 from style_guide. Existing environments are
    upgraded explicitly by scripts/seed_prompt_version.py; reading a prompt
    must never mutate editorial configuration at runtime.
    """
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is None:
        return _create_active(db, notes=PROMPT_V6_NOTES)

    return active
