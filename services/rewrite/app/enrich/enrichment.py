from __future__ import annotations

import logging

from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import AllKeysExhaustedError, call_with_rotation
from rewrite_app.rewrite.schemas import EnrichResultSchema
from rewrite_app.settings import RewriteSettings
from common.token_usage import TokenUsage
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Regenerate-on-invalid-JSON budget (ТЗ §4.20) — after this many failed
# attempts the caller dead-letters instead of retrying forever.
MAX_ATTEMPTS = 3

ENRICH_SYSTEM_PROMPT = """\
Ты извлекаешь структурированные факты из новостных материалов об одном
инфоповоде (кластер источников, возможно на разных языках) для UNUM
(theunum.io). НЕ переписывай текст — только извлекай факты из того, что
дано, ничего не додумывай.

Верни строго один JSON-объект по схеме:
{
  "facts": [{"kind": "who|what|when|number|quote", "text": "..."}],
  "press_release": <bool>,
  "regulated": <bool>,
  "market_sensitive": <bool>,
  "fact_conflict": <bool>,
  "fact_conflict_note": "<если fact_conflict — в чём именно источники расходятся>"
}
- press_release: материал похож на официальный пресс-релиз компании/проекта.
- regulated: касается регулирования или регуляторов (SEC, CFTC, MiCA и т.п.).
- market_sensitive: может повлиять на рыночные/инвестиционные решения.
- fact_conflict: источники в кластере расходятся в конкретной цифре, дате
  или имени — существенно, а не на уровне погрешности (не расходятся в
  тоне/акцентах — только в фактах). Разные цифры/цены, объяснимые просто
  разным временем публикации источников (например, курс актива за
  несколько минут/часов) — это НЕ конфликт, если источники не утверждают
  взаимоисключающее об одном и том же моменте времени.
Без markdown-разметки, без текста до/после JSON.
"""


def enrich_cluster(
    db: Session, settings: RewriteSettings, *, sources_text: str
) -> tuple[EnrichResultSchema, str, str, TokenUsage]:
    """Returns (result, key_alias_used, model_used, token_usage). Raises RuntimeError
    after MAX_ATTEMPTS failed regenerate attempts — caller writes the
    dead-letter record (ТЗ §4.20)."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content, key_alias, model, token_usage = call_with_rotation(
                db,
                api_keys=settings.llm_provider_keys(),
                system_prompt=ENRICH_SYSTEM_PROMPT,
                user_prompt=f"Источники кластера:\n\n{sources_text}",
                anthropic_model=settings.anthropic_model,
                openai_model=settings.openai_model,
            )
            data = extract_json(content)
            return EnrichResultSchema.model_validate(data), key_alias, model, token_usage
        except AllKeysExhaustedError:
            raise  # no point regenerating — no key can even be reached
        except (ValueError, KeyError) as exc:
            logger.warning("enrich attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc)
            last_error = exc
    raise RuntimeError(f"EnrichCluster failed after {MAX_ATTEMPTS} attempts: {last_error}")
