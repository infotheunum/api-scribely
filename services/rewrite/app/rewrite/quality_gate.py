from __future__ import annotations

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import call_with_rotation

SYSTEM_PROMPT = """Ты — строгий фактчекер. Сверь ОРИГИНАЛЫ и РЕРАЙТ.
Одобри только если ключевые факты, имена, цифры и даты переданы верно; нет
выдуманных фактов, инвестиционных рекомендаций, URL/названий источников и
оценочного политического контекста. Верни строго JSON:
{"approved": true|false, "issues": ["конкретная проблема или рекомендация"]}.
Не оценивай стиль и синонимы; проверяй смысл, полноту и редакционные запреты."""


def review_rewrite(db, settings, *, sources_text: str, rewritten_text: str):
    content, key_alias, model, usage = call_with_rotation(
        db,
        api_keys=settings.llm_provider_keys(),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"ОРИГИНАЛЫ:\n{sources_text}\n\nРЕРАЙТ:\n{rewritten_text}",
        anthropic_model=settings.anthropic_model,
        openai_model=settings.openai_model,
        qwen_model=settings.qwen_model,
        qwen_base_url=settings.qwen_base_url,
        advance=True,
    )
    data = extract_json(content)
    if not isinstance(data.get("approved"), bool):
        raise ValueError("quality gate did not return approved boolean")
    issues = data.get("issues", [])
    if not isinstance(issues, list) or not all(isinstance(item, str) for item in issues):
        raise ValueError("quality gate returned invalid issues")
    return data["approved"], issues, key_alias, model, usage
