from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT, V15_FIDELITY_APPENDIX
from sqlalchemy import select
from sqlalchemy.orm import Session

PROMPT_V14_NOTES = (
    "v14 — atomic number/date bindings, no invented facts or investment advice, "
    "political exclusion and RU terminology safeguards; seeded 2026-09-15"
)
PROMPT_V15_NOTES = (
    "v15 — preserves the active editorial prompt and adds a no-invented-year, "
    "quote-attribution and name-verification appendix; seeded 2026-09-16"
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

    Fresh DB: bootstrap v14 from style_guide. Existing environments are
    upgraded explicitly by scripts/seed_prompt_version.py; reading a prompt
    must never mutate editorial configuration at runtime.
    """
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is None:
        return _create_active(db, notes=PROMPT_V14_NOTES)

    return active


def create_v15_from_active(db: Session) -> PromptVersion:
    """Create a reviewable v15 candidate by extending, never replacing, v14."""
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V15_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V15_FIDELITY_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V15_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
