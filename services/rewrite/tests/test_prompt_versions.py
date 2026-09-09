from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT
from rewrite_app.prompt.versions import (
    PROMPT_V6_NOTES,
    get_active_prompt_version,
)


def test_fresh_db_bootstraps_v6(clean_db):
    version = get_active_prompt_version(clean_db)
    assert version.status == PromptVersionStatus.ACTIVE
    assert version.notes == PROMPT_V6_NOTES
    assert "ВЕРНОСТЬ ФАКТАМ" in version.template
    assert "НЕЙТРАЛЬНОСТЬ" in version.template
    assert "АТРИБУЦИЯ И ССЫЛКИ" in version.template
    assert "Не используй тире как связку мыслей" in version.template
    assert "англицизмы русскими эквивалентами" in version.template
    assert "максимум на ДВА" in version.template
    assert "транзакция" in version.template
    assert version.template == SYSTEM_PROMPT


def test_factory_v5_auto_upgrades_to_v6(clean_db):
    old = PromptVersion(
        template="old v5 template without source-grounding block",
        status=PromptVersionStatus.ACTIVE,
        notes="v5 — editorial quality: RU terminology and typography, "
        "two-source factual rewrite; seeded 2026-09-08",
    )
    clean_db.add(old)
    clean_db.commit()

    version = get_active_prompt_version(clean_db)
    assert version.id != old.id
    assert version.notes == PROMPT_V6_NOTES
    assert "НЕЙТРАЛЬНОСТЬ" in version.template
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
