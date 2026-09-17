from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from common.rewrite_body_limits import BODY_TARGET_MAX, BODY_TARGET_MIN
from common.rewrite_output_locales import (
    fill_inactive_locale_fields,
    get_output_locales,
    locale_enabled,
)
from common.seo_review import review_draft_seo
from common.site_categories import site_category_prompt_block
from common.token_usage import TokenUsage
from db.app_settings import get_setting
from db.models import PromptVersion
from pydantic import ValidationError
from rewrite_app.prompt.style_guide import (
    BODY_LENGTH_RULE,
    BODY_MIN_CHARS,
    BODY_SOFT_MAX_CHARS,
    REWRITE_FIDELITY_CONTRACT,
)
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.quality_gate import review_rewrite
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.rewrite.schemas import RewriteResultSchema
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# One retry is enough once hard-min matches typical first-pass length.
MAX_ATTEMPTS = 2
QUALITY_REQUIRED_FACT_LIMIT = 4


def _quality_required_facts(facts_text: str) -> str:
    """Choose a reviewable critical-fact set without hiding the full registry.

    Enrichment intentionally extracts every number and date. Requiring a critic
    to emit a JSON verdict for 15–25 items made the response truncate and
    stopped the whole dispatch queue. The rewrite still receives every fact;
    this bounded subset is only the strict publish gate.
    """
    lines = [line for line in facts_text.splitlines() if line.lstrip().startswith("- [")]
    if len(lines) <= QUALITY_REQUIRED_FACT_LIMIT:
        return facts_text

    selected: list[str] = []
    # A four-item response is reliable for the configured reviewer and covers
    # the event, its principal actor, timing and its most material figure.
    for kind in ("essence", "who", "when", "number", "what"):
        marker = f"- [{kind}]"
        match = next((line for line in lines if line.lstrip().startswith(marker)), None)
        if match and match not in selected:
            selected.append(match)

    for line in lines:
        if len(selected) >= QUALITY_REQUIRED_FACT_LIMIT:
            break
        if line not in selected:
            selected.append(line)
    return "\n".join(selected[:QUALITY_REQUIRED_FACT_LIMIT])


@dataclass(frozen=True)
class BodyLengthProfile:
    """Prompt-only target derived from the supplied source, not its summary."""

    source_chars: int
    target_min: int
    target_max: int


def _body_length_profile(sources_text: str) -> BodyLengthProfile:
    """Keep substantive rewrites proportional to the supplied source corpus.

    ``sources_text`` can contain two sources.  We deliberately use its total size:
    the model may use facts from both texts, while the upper band keeps a cluster
    with repeated wire copy from producing an excessively long article.
    """
    source_chars = len(sources_text.strip())
    if source_chars <= 2200:
        return BodyLengthProfile(source_chars, BODY_TARGET_MIN, BODY_TARGET_MAX)
    if source_chars <= 5000:
        return BodyLengthProfile(source_chars, 2400, 3600)
    return BodyLengthProfile(source_chars, 3000, 4500)


def _is_body_length_error(exc: ValidationError) -> bool:
    """Whether the previous structured answer can be safely length-edited."""
    return any(
        "must be at least" in (message := str(error.get("msg", "")))
        and ("body_en" in message or "body_ru" in message)
        for error in exc.errors()
    )


def _output_schema_hint(locales: list[str], profile: BodyLengthProfile) -> str:
    """JSON shape for the model — only active locales need full text."""
    lines = [
        "Верни строго один JSON-объект (без markdown, без текста до/после) по этой схеме:",
        "{",
    ]
    if locale_enabled(locales, "en"):
        lines.append(
            f'  "title_en": "...", "body_en": "... (цель {profile.target_min}-{profile.target_max}, '
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
            f'  "title_ru": "...", "body_ru": "... (цель {profile.target_min}-{profile.target_max}, '
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


def _body_length_rule(locales: list[str], profile: BodyLengthProfile) -> str:
    parts: list[str] = []
    if locale_enabled(locales, "en"):
        parts.append(
            f"- body_en: цель {profile.target_min}–{profile.target_max}, "
            f"hard-min {BODY_MIN_CHARS} (свыше {BODY_SOFT_MAX_CHARS} ок), "
            "ровно 3 абзаца через \\n\\n"
        )
    if locale_enabled(locales, "ru"):
        parts.append(
            f"- body_ru: цель {profile.target_min}–{profile.target_max}, "
            f"hard-min {BODY_MIN_CHARS} (свыше {BODY_SOFT_MAX_CHARS} ок), "
            "ровно 3 абзаца через \\n\\n"
        )
    if not parts:
        return BODY_LENGTH_RULE
    return (
        "ОБЪЁМ ТЕЛА (цель зависит от объема исходников; ниже hard-min = regenerate; "
        "верхнего reject нет):\n" + "\n".join(parts) + f"\n- Активные языки: {', '.join(locales)}. "
        "Не генерируй текст на выключенных языках."
        f"\n- В исходниках передано около {profile.source_chars} символов. "
        f"Стремись к {profile.target_min}–{profile.target_max}; "
        f"минимум {BODY_MIN_CHARS}."
    )


def _build_user_prompt(
    *,
    sources_text: str,
    facts_text: str,
    flags_text: str,
    style_overlay_note: str,
    locales: list[str],
    profile: BodyLengthProfile,
) -> str:
    return (
        f"Источники кластера:\n{sources_text}\n\n"
        f"Извлечённые факты:\n{facts_text}\n\n"
        f"Флаги контекста:\n{flags_text}\n\n"
        f"{style_overlay_note}\n\n"
        f"{_output_schema_hint(locales, profile)}"
    )


def _reviewable_rewrite_text(result: RewriteResultSchema) -> str:
    """Send every public text field to the editor, not just the article body."""
    return json.dumps(
        {
            "title_en": result.title_en,
            "body_en": result.body_en,
            "title_en_variants": result.title_en_variants,
            "seo_en": result.seo_en.model_dump(),
            "title_ru": result.title_ru,
            "body_ru": result.body_ru,
            "title_ru_variants": result.title_ru_variants,
            "seo_ru": result.seo_ru.model_dump(),
            "tags": [tag.model_dump() for tag in result.tags],
        },
        ensure_ascii=False,
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
) -> tuple[RewriteResultSchema, str, str, TokenUsage, dict]:
    """Returns (result, key_alias_used, model_used, token_usage). Raises RuntimeError
    after MAX_ATTEMPTS failed regenerate attempts (ТЗ §4.20 dead-letter)."""
    locales = get_output_locales(db)
    quality_required_facts = _quality_required_facts(facts_text)
    profile = _body_length_profile(sources_text)
    user_prompt = _build_user_prompt(
        sources_text=sources_text,
        facts_text=facts_text,
        flags_text=flags_text,
        style_overlay_note=style_overlay_note,
        locales=locales,
        profile=profile,
    )

    system_prompt = (
        f"{prompt_version.template.rstrip()}\n\n{_body_length_rule(locales, profile)}\n\n"
        f"{REWRITE_FIDELITY_CONTRACT}\n\n"
        f"{site_category_prompt_block(db)}"
    )
    last_error: Exception | None = None
    retry_note = ""
    previous_draft_json = ""
    provider_keys = settings.llm_provider_keys()
    length_editor_active = False
    active_bodies = " и ".join(
        name
        for name, code in (("body_en", "en"), ("body_ru", "ru"))
        if locale_enabled(locales, code)
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            editor_preferred_alias = (
                "anthropic"
                if length_editor_active and provider_keys.get("anthropic")
                else prefer_key_alias
            )
            content, key_alias, model, token_usage = call_with_rotation(
                db,
                api_keys=provider_keys,
                system_prompt=system_prompt,
                user_prompt=user_prompt + retry_note,
                anthropic_model=settings.anthropic_model,
                openai_model=settings.openai_model,
                qwen_model=settings.qwen_model,
                qwen_base_url=settings.qwen_base_url,
                prefer_key_alias=editor_preferred_alias,
                advance=False,
            )
            data = fill_inactive_locale_fields(extract_json(content), locales)
            previous_draft_json = json.dumps(data, ensure_ascii=False)
            result = RewriteResultSchema.model_validate(data, context={"locales": locales})
            hint = f"{result.title_en} {result.body_en} {result.title_ru} {result.body_ru}"
            from common.site_categories import resolve_site_category_slug

            result.suggested_category_slug = resolve_site_category_slug(
                result.suggested_category_slug,
                db=db,
                hint_text=hint,
            )
            seo_review_report = review_draft_seo(
                title_en=result.title_en,
                body_en=result.body_en,
                seo_title_en=result.seo_en.seo_title,
                seo_description_en=result.seo_en.seo_description,
                focus_keyphrase_en=result.seo_en.focus_keyphrase,
                title_ru=result.title_ru,
                body_ru=result.body_ru,
                seo_title_ru=result.seo_ru.seo_title,
                seo_description_ru=result.seo_ru.seo_description,
                focus_keyphrase_ru=result.seo_ru.focus_keyphrase,
            )
            review_report: dict = {}
            if bool(get_setting(db, "quality_gate.enabled", False)):
                approved, issues, review_report, _, _, quality_usage = review_rewrite(
                    db,
                    settings,
                    sources_text=sources_text,
                    required_facts_text=quality_required_facts,
                    rewritten_text=_reviewable_rewrite_text(result),
                    translate_sources=bool(get_setting(db, "review.translate_originals.enabled", False)),
                )
                review_report["all_extracted_facts"] = facts_text
                review_report["quality_gate_required_facts"] = quality_required_facts
                if not approved:
                    raise ValueError("quality gate failed: " + "; ".join(issues[:8]))
                token_usage += quality_usage
            review_report["seo_review_report"] = seo_review_report
            return result, key_alias, model, token_usage, review_report
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
            if _is_body_length_error(exc) and previous_draft_json:
                length_editor_active = True
                retry_note = (
                    "\n\nРЕДАКТОРСКИЙ ПРОХОД ПО ДЛИНЕ. Ниже предыдущий JSON-черновик, "
                    "который нельзя заменять новым сюжетом. Верни полный JSON в той же схеме. "
                    f"Расширь {active_bodies} до {profile.target_min}–{profile.target_max} символов "
                    f"(но не менее {BODY_MIN_CHARS + 100}), "
                    "сохранив все подтвержденные факты, даты, цифры, имена и три абзаца. "
                    "Дополняй только сведениями из исходных материалов; не добавляй новых фактов "
                    "и не меняй смысл.\n\n"
                    f"ПРЕДЫДУЩИЙ_JSON:\n{previous_draft_json}"
                )
            else:
                length_editor_active = False
                retry_note = (
                    f"\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: {str(exc)[:400]}. "
                    f"{active_bodies}: hard-min {BODY_MIN_CHARS} "
                    f"(цель {profile.target_min}–{profile.target_max}; "
                    f"свыше {BODY_SOFT_MAX_CHARS} допустимо), ровно 3 абзаца "
                    f"через \\n\\n. Активные языки: {', '.join(locales)}. "
                    f"Если коротко — РАСШИРЬ тот же смысл только материалом "
                    f"из источников (контекст, атрибуция, пояснения). "
                    f"НЕ выдумывай цифры/%/суммы/даты и НЕ меняй сюжет."
                )
        except (ValueError, KeyError) as exc:
            logger.warning(
                "rewrite attempt %d/%d failed: %s",
                attempt,
                MAX_ATTEMPTS,
                exc,
            )
            last_error = exc
            if previous_draft_json:
                length_editor_active = True
                retry_note = (
                    f"\n\nРЕДАКТОРСКИЙ ПРОХОД ПО ФАКТАМ. Замечания проверки: {str(exc)[:1200]}. "
                    "Ниже предыдущий JSON-черновик. Верни полный JSON в той же схеме, "
                    "исправь только перечисленные нарушения по исходным материалам и сохрани "
                    "остальной подтвержденный смысл. Не добавляй неподтвержденных фактов, "
                    "цифр, дат, имён или источников.\n\n"
                    f"ПРЕДЫДУЩИЙ_JSON:\n{previous_draft_json}"
                )
            else:
                retry_note = (
                    f"\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН ПРОВЕРКОЙ: {str(exc)[:1200]}. "
                    "Исправь только перечисленные нарушения, сверяясь с оригиналами. "
                    "Не добавляй новых фактов, цифр, дат, имён или источников."
                )
    raise RuntimeError(f"RewriteCluster failed after {MAX_ATTEMPTS} attempts: {last_error}")
