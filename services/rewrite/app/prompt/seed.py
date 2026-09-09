"""Seed and activate the current factory PromptVersion.

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
    version = db.scalar(select(PromptVersion).where(PromptVersion.notes == PROMPT_V6_NOTES))
    if version is None:
        version = PromptVersion(
            template=SYSTEM_PROMPT,
            status=PromptVersionStatus.DRAFT,
            notes=PROMPT_V6_NOTES,
        )
        db.add(version)
        db.flush()

    for active in db.scalars(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    ):
        if active.id != version.id:
            active.status = PromptVersionStatus.RETIRED
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
