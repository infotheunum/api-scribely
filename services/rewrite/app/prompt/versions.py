from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import (
    SYSTEM_PROMPT,
    V15_FIDELITY_APPENDIX,
    V16_EDITORIAL_STYLE_APPENDIX,
    V17_READABILITY_APPENDIX,
    V18_RU_EDITORIAL_PRECISION_APPENDIX,
    V19_FACTUAL_COVERAGE_APPENDIX,
    V20_FACT_PROPORTIONAL_VOLUME_APPENDIX,
)
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
PROMPT_V16_NOTES = (
    "v16 — preserves the active editorial prompt and adds natural Russian style, "
    "terminology and SEO-quality safeguards; seeded 2026-09-17"
)

PROMPT_V17_NOTES = (
    "v17 — preserves the active editorial prompt and adds readable news style, "
    "active voice and source-grounded context safeguards; seeded 2026-09-17"
)
PROMPT_V18_NOTES = (
    "v18 — preserves the active editorial prompt and adds Russian word-order, "
    "punctuation and final fidelity safeguards; seeded 2026-09-18"
)
PROMPT_V19_NOTES = (
    "v19 — preserves the active editorial prompt and enforces source-block "
    "coverage over generic rewrite prose; seeded 2026-09-18"
)
PROMPT_V20_NOTES = (
    "v20 — fact-proportional length and flexible paragraph structure; seeded 2026-09-18"
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


def create_v16_from_active(db: Session) -> PromptVersion:
    """Create a reviewable v16 candidate without replacing the active template."""
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V16_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V16_EDITORIAL_STYLE_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V16_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def create_v17_from_active(db: Session) -> PromptVersion:
    """Create a reviewable v17 candidate without replacing the active template."""
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V17_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V17_READABILITY_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V17_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def create_v18_from_active(db: Session) -> PromptVersion:
    """Create a reviewable v18 candidate without replacing the active template."""
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V18_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V18_RU_EDITORIAL_PRECISION_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V18_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def create_v19_from_active(db: Session) -> PromptVersion:
    """Create a reviewable v19 candidate without replacing the active template."""
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V19_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V19_FACTUAL_COVERAGE_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V19_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def create_v20_from_active(db: Session) -> PromptVersion:
    existing = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V20_NOTES))
    if existing is not None:
        return existing
    active = get_active_prompt_version(db)
    version = PromptVersion(
        template=f"{active.template.rstrip()}\n\n{V20_FACT_PROPORTIONAL_VOLUME_APPENDIX}",
        status=PromptVersionStatus.DRAFT,
        notes=PROMPT_V20_NOTES,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
