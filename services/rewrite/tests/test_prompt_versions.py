from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.seed import seed
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


def test_existing_active_prompt_is_not_changed_at_runtime(clean_db):
    old = PromptVersion(
        template="old v5 template without source-grounding block",
        status=PromptVersionStatus.ACTIVE,
        notes="v5 — editorial quality: RU terminology and typography, "
        "two-source factual rewrite; seeded 2026-09-08",
    )
    clean_db.add(old)
    clean_db.commit()

    version = get_active_prompt_version(clean_db)
    assert version.id == old.id
    assert version.status == PromptVersionStatus.ACTIVE


def test_seed_activates_v6_and_is_idempotent(clean_db):
    old = PromptVersion(template="old", status=PromptVersionStatus.ACTIVE, notes="v5")
    clean_db.add(old)
    clean_db.commit()

    first = seed(clean_db)
    second = seed(clean_db)

    assert first.id == second.id
    assert second.status == PromptVersionStatus.ACTIVE
    assert second.notes == PROMPT_V6_NOTES
    assert clean_db.query(PromptVersion).filter_by(notes=PROMPT_V6_NOTES).count() == 1
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
