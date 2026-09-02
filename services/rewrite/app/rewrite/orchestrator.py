from __future__ import annotations

import logging

from db.models import PromptVersion
from pydantic import ValidationError
from common.site_categories import site_category_prompt_block
from rewrite_app.prompt.style_guide import BODY_LENGTH_RULE, BODY_MAX_CHARS, BODY_MIN_CHARS
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.rewrite.schemas import RewriteResultSchema
from rewrite_app.settings import RewriteSettings
from common.token_usage import TokenUsage
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

# Kept close to the Pydantic schema on purpose — the model is far more
# likely to produce a valid response when shown the exact shape than
# when the shape is only prose-described.
OUTPUT_SCHEMA_HINT = f"""\
Верни строго один JSON-объект (без markdown, без текста до/после) по
этой схеме:
{{
  "title_en": "...", "body_en": "... ({BODY_MIN_CHARS}-{BODY_MAX_CHARS} символов, 3 абзаца)",
  "title_ru": "...", "body_ru": "... ({BODY_MIN_CHARS}-{BODY_MAX_CHARS} символов, 3 абзаца)",
  "title_en_variants": ["...", "..."],
  "title_ru_variants": ["...", "..."],
  "sponsor_flag": <bool>, "press_release_flag": <bool>, "disclaimer_flag": <bool>,
  "suggested_category_slug": "... (один slug из списка категорий CMS в system prompt)",
  "tags": [{{"slug": "...", "name": "..."}}],
  "seo_en": {{
    "seo_title": "...", "seo_description": "...", "slug": "...",
    "og_title": "...", "og_description": "...",
    "focus_keyphrase": "...", "keywords": ["...", "..."]
  }},
  "seo_ru": {{ /* same shape as seo_en, in Russian */ }},
  "image_brief": {{
    "image_brief": "...", "image_mood": "...", "image_subjects": ["..."],
    "image_style": "...", "image_do_not": ["..."],
    "image_alt": "...", "image_caption": "...", "image_source_suggestion": "..."
  }}
}}
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
) -> tuple[RewriteResultSchema, str, str, TokenUsage]:
    """Returns (result, key_alias_used, model_used, token_usage). Raises RuntimeError
    after MAX_ATTEMPTS failed regenerate attempts (ТЗ §4.20 dead-letter)."""
    user_prompt = _build_user_prompt(
        sources_text=sources_text,
        facts_text=facts_text,
        flags_text=flags_text,
        style_overlay_note=style_overlay_note,
    )

    system_prompt = (
        f"{prompt_version.template.rstrip()}\n\n{BODY_LENGTH_RULE}\n\n"
        f"{site_category_prompt_block(db)}"
    )
    last_error: Exception | None = None
    retry_note = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content, key_alias, model, token_usage = call_with_rotation(
                db,
                api_keys=settings.llm_provider_keys(),
                system_prompt=system_prompt,
                user_prompt=user_prompt + retry_note,
                anthropic_model=settings.anthropic_model,
                openai_model=settings.openai_model,
            )
            data = extract_json(content)
            result = RewriteResultSchema.model_validate(data)
            hint = f"{result.title_en} {result.body_en} {result.title_ru} {result.body_ru}"
            from common.site_categories import resolve_site_category_slug

            result.suggested_category_slug = resolve_site_category_slug(
                result.suggested_category_slug,
                db=db,
                hint_text=hint,
            )
            return result, key_alias, model, token_usage
        except AllKeysExhaustedError:
            raise
        except ValidationError as exc:
            logger.warning("rewrite attempt %d/%d validation failed: %s", attempt, MAX_ATTEMPTS, exc)
            last_error = exc
            retry_note = (
                f"\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: {str(exc)[:400]}. "
                f"body_en и body_ru должны быть {BODY_MIN_CHARS}–{BODY_MAX_CHARS} символов каждый "
                f"(считай с пробелами) и ровно 3 абзаца через \\n\\n. "
                f"Если текст короткий — допиши контекст, цифры и реакцию рынка; не сокращай. "
                f"Перегенерируй полностью."
            )
        except (ValueError, KeyError) as exc:
            logger.warning("rewrite attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
            last_error = exc
    raise RuntimeError(f"RewriteCluster failed after {MAX_ATTEMPTS} attempts: {last_error}")
