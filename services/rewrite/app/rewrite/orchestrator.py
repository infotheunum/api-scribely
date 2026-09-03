from __future__ import annotations

import logging

from common.rewrite_body_limits import BODY_TARGET_MAX, BODY_TARGET_MIN
from common.rewrite_output_locales import (
    fill_inactive_locale_fields,
    get_output_locales,
    locale_enabled,
)
from common.site_categories import site_category_prompt_block
from common.token_usage import TokenUsage
from db.models import PromptVersion
from pydantic import ValidationError
from rewrite_app.prompt.style_guide import BODY_LENGTH_RULE, BODY_MAX_CHARS, BODY_MIN_CHARS
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.rewrite.schemas import RewriteResultSchema
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# One retry is enough once hard-min matches typical first-pass length.
MAX_ATTEMPTS = 2


def _output_schema_hint(locales: list[str]) -> str:
    """JSON shape for the model — only active locales need full text."""
    lines = [
        "Верни строго один JSON-объект (без markdown, без текста до/после) по этой схеме:",
        "{",
    ]
    if locale_enabled(locales, "en"):
        lines.append(
            f'  "title_en": "...", "body_en": "... (цель {BODY_TARGET_MIN}-{BODY_TARGET_MAX}, '
            f'min {BODY_MIN_CHARS}, 3 абзаца)",'
        )
        lines.append('  "title_en_variants": ["...", "..."],')
        lines.append(
            '  "seo_en": {"seo_title": "...", "seo_description": "...", "slug": "...", '
            '"og_title": "...", "og_description": "...", "focus_keyphrase": "...", '
            '"keywords": ["...", "..."]},'
        )
    else:
        lines.append(
            '  "title_en": "", "body_en": "", "title_en_variants": [], '
            '"seo_en": {"seo_title": "", "seo_description": "", "slug": "", '
            '"og_title": "", "og_description": "", "focus_keyphrase": "", "keywords": []},'
        )
    if locale_enabled(locales, "ru"):
        lines.append(
            f'  "title_ru": "...", "body_ru": "... (цель {BODY_TARGET_MIN}-{BODY_TARGET_MAX}, '
            f'min {BODY_MIN_CHARS}, 3 абзаца)",'
        )
        lines.append('  "title_ru_variants": ["...", "..."],')
        lines.append(
            '  "seo_ru": {"seo_title": "...", "seo_description": "...", "slug": "...", '
            '"og_title": "...", "og_description": "...", "focus_keyphrase": "...", '
            '"keywords": ["...", "..."]},'
        )
    else:
        lines.append(
            '  "title_ru": "", "body_ru": "", "title_ru_variants": [], '
            '"seo_ru": {"seo_title": "", "seo_description": "", "slug": "", '
            '"og_title": "", "og_description": "", "focus_keyphrase": "", "keywords": []},'
        )
    lines.extend(
        [
            '  "sponsor_flag": <bool>, "press_release_flag": <bool>, "disclaimer_flag": <bool>,',
            '  "suggested_category_slug": "... (slug из списка категорий CMS)",',
            '  "tags": [{"slug": "...", "name": "..."}],',
            '  "image_brief": {',
            '    "image_brief": "...", "image_mood": "...", "image_subjects": ["..."],',
            '    "image_style": "...", "image_do_not": ["..."],',
            '    "image_alt": "...", "image_caption": "...", "image_source_suggestion": "..."',
            "  }",
            "}",
            f"Генерируй полноценный текст ТОЛЬКО для локалей: {', '.join(locales)}. "
            "Для остальных языков оставь пустые строки как в схеме выше.",
        ]
    )
    return "\n".join(lines)


def _body_length_rule(locales: list[str]) -> str:
    parts: list[str] = []
    if locale_enabled(locales, "en"):
        parts.append(
            f"- body_en: цель {BODY_TARGET_MIN}–{BODY_TARGET_MAX}, hard-gate "
            f"{BODY_MIN_CHARS}–{BODY_MAX_CHARS}, ровно 3 абзаца через \\n\\n"
        )
    if locale_enabled(locales, "ru"):
        parts.append(
            f"- body_ru: цель {BODY_TARGET_MIN}–{BODY_TARGET_MAX}, hard-gate "
            f"{BODY_MIN_CHARS}–{BODY_MAX_CHARS}, ровно 3 абзаца через \\n\\n"
        )
    if not parts:
        return BODY_LENGTH_RULE
    return (
        "ОБЪЁМ ТЕЛА (цель vs hard-gate; ниже hard-min = regenerate):\n"
        + "\n".join(parts)
        + f"\n- Активные языки: {', '.join(locales)}. "
        "Не генерируй текст на выключенных языках."
        f"\n- Стремись к {BODY_TARGET_MIN}–{BODY_TARGET_MAX}; "
        f"минимум {BODY_MIN_CHARS}, максимум {BODY_MAX_CHARS}."
    )


def _build_user_prompt(
    *,
    sources_text: str,
    facts_text: str,
    flags_text: str,
    style_overlay_note: str,
    locales: list[str],
) -> str:
    return (
        f"Источники кластера:\n{sources_text}\n\n"
        f"Извлечённые факты:\n{facts_text}\n\n"
        f"Флаги контекста:\n{flags_text}\n\n"
        f"{style_overlay_note}\n\n"
        f"{_output_schema_hint(locales)}"
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
    prefer_key_alias: str | None = None,
) -> tuple[RewriteResultSchema, str, str, TokenUsage]:
    """Returns (result, key_alias_used, model_used, token_usage). Raises RuntimeError
    after MAX_ATTEMPTS failed regenerate attempts (ТЗ §4.20 dead-letter)."""
    locales = get_output_locales(db)
    user_prompt = _build_user_prompt(
        sources_text=sources_text,
        facts_text=facts_text,
        flags_text=flags_text,
        style_overlay_note=style_overlay_note,
        locales=locales,
    )

    system_prompt = (
        f"{prompt_version.template.rstrip()}\n\n{_body_length_rule(locales)}\n\n"
        f"{site_category_prompt_block(db)}"
    )
    last_error: Exception | None = None
    retry_note = ""
    active_bodies = " и ".join(
        name
        for name, code in (("body_en", "en"), ("body_ru", "ru"))
        if locale_enabled(locales, code)
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content, key_alias, model, token_usage = call_with_rotation(
                db,
                api_keys=settings.llm_provider_keys(),
                system_prompt=system_prompt,
                user_prompt=user_prompt + retry_note,
                anthropic_model=settings.anthropic_model,
                openai_model=settings.openai_model,
                qwen_model=settings.qwen_model,
                qwen_base_url=settings.qwen_base_url,
                prefer_key_alias=prefer_key_alias,
                advance=False,
            )
            data = fill_inactive_locale_fields(extract_json(content), locales)
            result = RewriteResultSchema.model_validate(data, context={"locales": locales})
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
            logger.warning(
                "rewrite attempt %d/%d validation failed: %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )
            last_error = exc
            retry_note = (
                f"\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: {str(exc)[:400]}. "
                f"{active_bodies}: hard-gate {BODY_MIN_CHARS}–{BODY_MAX_CHARS} "
                f"(цель {BODY_TARGET_MIN}–{BODY_TARGET_MAX}), ровно 3 абзаца "
                f"через \\n\\n. Активные языки: {', '.join(locales)}. "
                f"Если коротко — РАСШИРЬ тот же смысл (контекст, цифры, реакция), "
                f"не пиши с нуля другой сюжет. Если длинно — сожми без потери фактов."
            )
        except (ValueError, KeyError) as exc:
            logger.warning(
                "rewrite attempt %d/%d failed: %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )
            last_error = exc
    raise RuntimeError(f"RewriteCluster failed after {MAX_ATTEMPTS} attempts: {last_error}")
