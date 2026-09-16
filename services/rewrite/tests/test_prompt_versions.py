from __future__ import annotations

from db.enums import PromptVersionStatus
from db.models import PromptVersion
from rewrite_app.prompt.seed import seed
from rewrite_app.prompt.style_guide import SYSTEM_PROMPT, V15_FIDELITY_APPENDIX
from rewrite_app.prompt.versions import (
    PROMPT_V14_NOTES,
    PROMPT_V15_NOTES,
    create_v15_from_active,
    get_active_prompt_version,
)


def test_fresh_db_bootstraps_v14(clean_db):
    version = get_active_prompt_version(clean_db)
    assert version.status == PromptVersionStatus.ACTIVE
    assert version.notes == PROMPT_V14_NOTES
    assert "ВЕРНОСТЬ ФАКТАМ" in version.template
    assert "НЕЙТРАЛЬНОСТЬ" in version.template
    assert "АТРИБУЦИЯ И ССЫЛКИ" in version.template
    assert "Не используй тире как связку мыслей" in version.template
    assert "англицизмы русскими эквивалентами" in version.template
    assert "максимум на ДВА" in version.template
    assert "транзакция" in version.template
    assert "КАРТА ПРИВЯЗОК" in version.template
    assert "не равно «10 месяцев»" in version.template
    assert "инвестиционные рекомендации" in version.template
    assert "ТЕХНИЧЕСКАЯ ЧИСТОТА" in version.template
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


def test_seed_preserves_existing_active_prompt_and_is_idempotent(clean_db):
    old = PromptVersion(template="old", status=PromptVersionStatus.ACTIVE, notes="v5")
    clean_db.add(old)
    clean_db.commit()

    first = seed(clean_db)
    second = seed(clean_db)

    assert first.id == second.id
    assert second.status == PromptVersionStatus.ACTIVE
    assert second.notes == "v5"
    assert clean_db.query(PromptVersion).filter_by(notes=PROMPT_V14_NOTES).count() == 0
    clean_db.refresh(old)
    assert old.status == PromptVersionStatus.ACTIVE


def test_seed_bootstraps_v14_only_when_no_prompt_is_active(clean_db):
    version = seed(clean_db)

    assert version.status == PromptVersionStatus.ACTIVE
    assert version.notes == PROMPT_V14_NOTES


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


def test_v15_candidate_extends_active_prompt_without_replacing_it(clean_db):
    active = PromptVersion(
        template="working v13 rules",
        status=PromptVersionStatus.ACTIVE,
        notes="v13 — proven rules",
    )
    clean_db.add(active)
    clean_db.commit()

    candidate = create_v15_from_active(clean_db)

    assert candidate.status == PromptVersionStatus.DRAFT
    assert candidate.notes == PROMPT_V15_NOTES
    assert candidate.template == f"working v13 rules\n\n{V15_FIDELITY_APPENDIX}"
    assert clean_db.get(PromptVersion, active.id).status == PromptVersionStatus.ACTIVE
