from __future__ import annotations

import logging

from db.models import PromptVersion
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.rewrite.schemas import RewriteResultSchema
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

# Kept close to the Pydantic schema on purpose — the model is far more
# likely to produce a valid response when shown the exact shape than
# when the shape is only prose-described.
OUTPUT_SCHEMA_HINT = """\
Верни строго один JSON-объект (без markdown, без текста до/после) по
этой схеме:
{
  "title_en": "...", "body_en": "...",
  "title_ru": "...", "body_ru": "...",
  "title_en_variants": ["...", "..."],
  "title_ru_variants": ["...", "..."],
  "sponsor_flag": <bool>, "press_release_flag": <bool>, "disclaimer_flag": <bool>,
  "suggested_category_slug": "...",
  "tags": [{"slug": "...", "name": "..."}],
  "seo_en": {
    "seo_title": "...", "seo_description": "...", "slug": "...",
    "og_title": "...", "og_description": "...",
    "focus_keyphrase": "...", "keywords": ["...", "..."]
  },
  "seo_ru": { /* same shape as seo_en, in Russian */ },
  "image_brief": {
    "image_brief": "...", "image_mood": "...", "image_subjects": ["..."],
    "image_style": "...", "image_do_not": ["..."],
    "image_alt": "...", "image_caption": "...", "image_source_suggestion": "..."
  }
}
"""


def _build_user_prompt(
    *,
    sources_text: str,
    facts_text: str,
    flags_text: str,
    style_overlay_note: str,
) -> str:
    return (
        f"Источники кластера:\n{sources_text}\n\n"
        f"Извлечённые факты:\n{facts_text}\n\n"
        f"Флаги контекста:\n{flags_text}\n\n"
        f"{style_overlay_note}\n\n"
        f"{OUTPUT_SCHEMA_HINT}"
    )


def rewrite_cluster(
    db: Session,
    settings: RewriteSettings,
    prompt_version: PromptVersion,
    *,
    sources_text: str,
    facts_text: str,
    flags_text: str,
    style_overlay_note: str = "Оверлей стиля не назначен — используй house style.",
) -> tuple[RewriteResultSchema, str, str]:
    """Returns (result, key_alias_used, model_used). Raises RuntimeError
    after MAX_ATTEMPTS failed regenerate attempts (ТЗ §4.20 dead-letter)."""
    user_prompt = _build_user_prompt(
        sources_text=sources_text,
        facts_text=facts_text,
        flags_text=flags_text,
        style_overlay_note=style_overlay_note,
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content, key_alias, model = call_with_rotation(
                db,
                api_keys=settings.openrouter_keys(),
                system_prompt=prompt_version.template,
                user_prompt=user_prompt,
            )
            data = extract_json(content)
            return RewriteResultSchema.model_validate(data), key_alias, model
        except AllKeysExhaustedError:
            raise
        except (ValueError, KeyError) as exc:
            logger.warning("rewrite attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
            last_error = exc
    raise RuntimeError(f"RewriteCluster failed after {MAX_ATTEMPTS} attempts: {last_error}")
