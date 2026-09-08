from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from rewrite_app.prompt.versions import (
    PROMPT_V5_NOTES,
    get_active_prompt_version,
)


def test_fresh_db_bootstraps_v5(clean_db):
    version = get_active_prompt_version(clean_db)
    assert version.status == PromptVersionStatus.ACTIVE
    assert version.notes == PROMPT_V5_NOTES
    assert "ВЕРНОСТЬ ФАКТАМ" in version.template
    assert "максимум на ДВА" in version.template
    assert "транзакция" in version.template
    assert version.template == SYSTEM_PROMPT


def test_factory_v4_auto_upgrades_to_v5(clean_db):
    old = PromptVersion(
        template="old v4 template without editorial quality block",
        status=PromptVersionStatus.ACTIVE,
        notes="v4 — factual fidelity: exact numbers, no invented figures, "
        "preserve news essence over SEO padding; seeded 2026-09-04",
    )
    clean_db.add(old)
    clean_db.commit()

    version = get_active_prompt_version(clean_db)
    assert version.id != old.id
    assert version.notes == PROMPT_V5_NOTES
    assert "ИСТОЧНИКИ И ПРИОРИТЕТ ФАКТОВ" in version.template
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
