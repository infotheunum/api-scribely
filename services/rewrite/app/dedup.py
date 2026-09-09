from __future__ import annotations

import logging

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Ты проверяешь, описывают ли два набора новостных материалов ОДИН И ТОТ ЖЕ
инфоповод. Сравни главное действие, участников, объект и дату только по
переданным текстам. Разные публикации, пересказы и обновления одного события
считай одним инфоповодом. Два разных действия одной компании, схожая тема или
совпадение отдельных имен — это разные инфоповоды.

При малейшем сомнении выбери false. Ничего не додумывай.
Верни строго JSON без markdown: {"same_event": true|false}.
"""


def _sources_text(label: str, sources) -> str:
    parts = [label]
    for source in sources:
        # A title plus the lede is sufficient for the classifier and bounds
        # the prompt when a cluster has accumulated many follow-up reports.
        text = (source.excerpt_or_full_text or source.title)[:2000]
        parts.append(f"Заголовок: {source.title}\nТекст: {text}")
    return "\n\n".join(parts)


def confirm_same_event(
    db: Session,
    settings: RewriteSettings,
    *,
    incoming_sources,
    candidate_sources,
) -> tuple[bool, str, str, TokenUsage]:
    """Return a conservative same-event decision for a semantic candidate."""
    user_prompt = "\n\n".join(
        (
            _sources_text("НОВЫЙ МАТЕРИАЛ:", incoming_sources),
            _sources_text("КАНДИДАТ НА СУЩЕСТВУЮЩИЙ КЛАСТЕР:", candidate_sources),
        )
    )
    try:
        content, key_alias, model, usage = call_with_rotation(
            db,
            api_keys=settings.llm_provider_keys(),
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            anthropic_model=settings.anthropic_model,
            openai_model=settings.openai_model,
            qwen_model=settings.qwen_model,
            qwen_base_url=settings.qwen_base_url,
            advance=True,
        )
        data = extract_json(content)
        if not isinstance(data.get("same_event"), bool):
            raise ValueError("same_event must be a boolean")
        return data["same_event"], key_alias, model, usage
    except AllKeysExhaustedError:
        raise
    except (ValueError, KeyError) as exc:
        logger.warning("duplicate confirmation rejected: %s", exc)
        raise RuntimeError(f"Duplicate confirmation failed: {exc}") from exc
