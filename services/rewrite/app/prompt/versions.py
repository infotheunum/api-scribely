from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_active_prompt_version(db: Session) -> PromptVersion:
    """Returns the active PromptVersion, bootstrapping v1 from the
    current style guide on first call if none exists yet. Normal
    operation activates new versions through Admin (ТЗ §4.13) — this
    self-heal only covers the very first run of a fresh database."""
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is not None:
        return active

    version = PromptVersion(
        template=SYSTEM_PROMPT,
        status=PromptVersionStatus.ACTIVE,
        notes="v1 — bootstrapped from docs/Правила_Рерайта_и_Стиля_Черновик.md (Фаза 4)",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
