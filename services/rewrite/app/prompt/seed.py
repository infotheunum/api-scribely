"""Seed the factory PromptVersion without overriding editorial configuration.

Run from the rewrite service before it starts serving gRPC. This is the only
production upgrade path for a shipped house prompt: reading a prompt never
changes editorial configuration at runtime. The seed is idempotent.
"""

from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.db import new_session
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from rewrite_app.prompt.versions import PROMPT_V6_NOTES
from sqlalchemy import select


def seed(db) -> PromptVersion:
    # The Admin-selected prompt is the source of truth. A service restart must
    # never silently retire it and resurrect the factory v6 template.
    active = db.scalar(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    )
    if active is not None:
        return active

    version = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V6_NOTES))
    if version is None:
        version = PromptVersion(
            template=SYSTEM_PROMPT,
            status=PromptVersionStatus.DRAFT,
            notes=PROMPT_V6_NOTES,
        )
        db.add(version)
        db.flush()

    version.template = SYSTEM_PROMPT
    version.status = PromptVersionStatus.ACTIVE
    db.commit()
    db.refresh(version)
    return version


def main() -> None:
    db = new_session()
    try:
        version = seed(db)
        print(f"active: {version.id} ({PROMPT_V6_NOTES})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
