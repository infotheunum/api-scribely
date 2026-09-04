from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from rewrite_app.prompt.versions import (
    PROMPT_V4_NOTES,
    get_active_prompt_version,
)


def test_fresh_db_bootstraps_v4(clean_db):
    version = get_active_prompt_version(clean_db)
    assert version.status == PromptVersionStatus.ACTIVE
    assert version.notes == PROMPT_V4_NOTES
    assert "ВЕРНОСТЬ ФАКТАМ" in version.template
    assert version.template == SYSTEM_PROMPT


def test_factory_v3_auto_upgrades_to_v4(clean_db):
    old = PromptVersion(
        template="old v3 template without fidelity block",
        status=PromptVersionStatus.ACTIVE,
        notes="v3 — RU-first SEO; body hard-min 1700, target 2000–2800",
    )
    clean_db.add(old)
    clean_db.commit()

    version = get_active_prompt_version(clean_db)
    assert version.id != old.id
    assert version.notes == PROMPT_V4_NOTES
    assert "ВЕРНОСТЬ ФАКТАМ" in version.template
    clean_db.refresh(old)
    assert old.status == PromptVersionStatus.RETIRED


def test_custom_admin_prompt_not_auto_upgraded(clean_db):
    custom = PromptVersion(
        template="custom editorial prompt",
        status=PromptVersionStatus.ACTIVE,
        notes="custom — tuned by admin 2026-09-01",
    )
    clean_db.add(custom)
    clean_db.commit()

    version = get_active_prompt_version(clean_db)
    assert version.id == custom.id
    assert version.template == "custom editorial prompt"
