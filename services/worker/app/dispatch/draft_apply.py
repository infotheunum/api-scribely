from __future__ import annotations

import uuid
from datetime import UTC, datetime

from common.site_categories import resolve_site_category_slug
from db.enums import DraftRevisionKind, DraftStatus
from db.models import Draft, DraftRevision
from sqlalchemy.orm import Session


def apply_rewrite_content(
    db: Session,
    draft: Draft,
    content,
    *,
    prompt_version_id: str | None,
    trace_id: str,
    rewrite_key_alias: str | None,
    rewrite_model: str | None,
    translate_key_alias: str | None,
    translate_model: str | None,
    revision_kind: DraftRevisionKind = DraftRevisionKind.AI_GENERATED,
    bump_version: bool = False,
    editorial_topic: str | None = None,
) -> None:
    """Overwrite an existing Draft from a RewriteCluster DraftContent proto."""
    draft.title_en = content.title_en
    draft.body_en = content.body_en
    draft.title_ru = content.title_ru
    draft.body_ru = content.body_ru
    draft.title_en_variants = list(content.title_en_variants)
    draft.title_ru_variants = list(content.title_ru_variants)
    draft.attribution_urls = list(content.attribution_urls)
    draft.sponsor_flag = content.sponsor_flag
    draft.press_release_flag = content.press_release_flag
    draft.disclaimer_flag = content.disclaimer_flag
    draft.fact_conflict = content.fact_conflict
    draft.rewrite_llm_key_alias = rewrite_key_alias
    draft.rewrite_llm_model = rewrite_model
    draft.translate_llm_key_alias = translate_key_alias
    draft.translate_llm_model = translate_model
    if prompt_version_id:
        draft.prompt_version_id = uuid.UUID(str(prompt_version_id))
    else:
        draft.prompt_version_id = None
    draft.trace_id = trace_id
    draft.seo_title_en = content.seo_en.seo_title
    draft.seo_description_en = content.seo_en.seo_description
    draft.slug_en = content.seo_en.slug
    draft.og_title_en = content.seo_en.og_title
    draft.og_description_en = content.seo_en.og_description
    draft.focus_keyphrase_en = content.seo_en.focus_keyphrase
    draft.keywords_en = list(content.seo_en.keywords)
    draft.seo_title_ru = content.seo_ru.seo_title
    draft.seo_description_ru = content.seo_ru.seo_description
    draft.slug_ru = content.seo_ru.slug
    draft.og_title_ru = content.seo_ru.og_title
    draft.og_description_ru = content.seo_ru.og_description
    draft.focus_keyphrase_ru = content.seo_ru.focus_keyphrase
    draft.keywords_ru = list(content.seo_ru.keywords)
    draft.image_brief = content.image_brief.image_brief
    draft.image_mood = content.image_brief.image_mood
    draft.image_subjects = list(content.image_brief.image_subjects)
    draft.image_style = content.image_brief.image_style
    draft.image_do_not = list(content.image_brief.image_do_not)
    draft.image_alt = content.image_brief.image_alt
    draft.image_caption = content.image_brief.image_caption
    draft.image_source_suggestion = content.image_brief.image_source_suggestion
    draft.pending_tags = [{"slug": t.slug, "name": t.name} for t in content.tags]
    hint_text = " ".join(
        part
        for part in (
            content.title_en,
            content.body_en,
            content.title_ru,
            content.body_ru,
            content.suggested_category_slug,
        )
        if part
    )
    draft.pending_category_slug = resolve_site_category_slug(
        content.suggested_category_slug,
        db=db,
        editorial_topic=editorial_topic,
        hint_text=hint_text,
    )

    draft.sensitive_hold = False
    draft.compliance_notes = []
    draft.similarity_score = None
    draft.status = DraftStatus.DRAFTING
    draft.content_generated_at = datetime.now(UTC)
    if bump_version:
        draft.version += 1

    db.add(
        DraftRevision(
            draft_id=draft.id,
            kind=revision_kind,
            title_en=content.title_en,
            body_en=content.body_en,
            title_ru=content.title_ru,
            body_ru=content.body_ru,
            prompt_version_id=uuid.UUID(str(prompt_version_id)) if prompt_version_id else None,
        )
    )
