from __future__ import annotations

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import call_with_rotation

SYSTEM_PROMPT = """Ты — строгий фактчекер и литературный редактор. Сверь ОРИГИНАЛЫ и
РЕРАЙТ. Одобри только если ключевые факты, имена, цифры и даты переданы верно;
нет выдуманных фактов, инвестиционных рекомендаций, URL/названий источников,
оценочного политического контекста, ошибок перевода, грамматики и неуместных
англицизмов в русской версии.

Упущения фиксируй в fact_checks, но НЕ отклоняй материал только из-за них:
текст ограничен по объему и не обязан повторять все детали длинного источника.
Никогда не ставь approved=true, если status «искажён» или «добавлено», при
любой реальной ошибке перевода, орфографии, грамматики или при англицизме,
который не является официальным названием, именем, тикером или аббревиатурой.
Также не одобряй инвестиционные рекомендации, URL/несогласованную атрибуцию и
оценочный политический контекст. Не придирайся к синонимам.

Верни строго JSON:
{"approved": true|false, "issues": ["конкретная проблема и точная правка"],
 "language_issues": ["ошибка перевода, грамматики или неуместный англицизм"],
 "blocking_issues": ["инвестиционная рекомендация, URL, источник или политическая оценка"],
 "fact_checks": [{"fact": "ключевой факт из оригинала", "status": "совпадает|упущен|искажён|добавлено", "severity": "critical|secondary", "rewrite_evidence": "как передано в рерайте"}],
 "translations": [{"title": "точный заголовок исходника", "body_ru": "полный перевод на русский"}]}.
Если ошибок нет, language_issues и blocking_issues должны быть пустыми массивами:
не пиши в них фразы «нет ошибок» или другие пояснения. Поле translations
заполняй только когда в запросе явно включён перевод."""

_BLOCKING_FACT_STATUSES = {"искажен", "добавлено"}


def _normalized_status(value: object) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"quality gate returned invalid {field}")
    return [item.strip() for item in value if item.strip()]


def _actual_findings(items: list[str]) -> list[str]:
    """Ignore a common LLM schema violation: prose saying that no errors exist."""
    no_finding_prefixes = (
        "нет ошибок",
        "ошибок нет",
        "не выявлено",
        "отсутствуют ошибки",
        "нарушений нет",
        "нет нарушений",
    )
    return [
        item
        for item in items
        if not item.lower().lstrip("«\"' ").startswith(no_finding_prefixes)
    ]


def _deterministic_review_issues(
    *, fact_checks: list[object], language_issues: list[str], blocking_issues: list[str]
) -> list[str]:
    """Do not let an internally inconsistent LLM verdict publish bad copy."""
    blocked = [*language_issues, *blocking_issues]
    for item in fact_checks:
        if not isinstance(item, dict):
            raise ValueError("quality gate returned invalid fact_checks")
        status = _normalized_status(item.get("status"))
        fact = str(item.get("fact") or "ключевой факт").strip()
        if status in _BLOCKING_FACT_STATUSES:
            blocked.append(f"{fact}: статус «{item.get('status')}»")
    return blocked


def review_rewrite(
    db, settings, *, sources_text: str, rewritten_text: str, translate_sources: bool
):
    content, key_alias, model, usage = call_with_rotation(
        db,
        api_keys=settings.llm_provider_keys(),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            f"ОРИГИНАЛЫ:\n{sources_text}\n\nРЕРАЙТ:\n{rewritten_text}\n\n"
            f"ПЕРЕВОД ОРИГИНАЛОВ: {'включён — верни полный перевод каждого исходника в translations' if translate_sources else 'выключен — верни translations как []'}"
        ),
        anthropic_model=settings.anthropic_model,
        openai_model=settings.openai_model,
        qwen_model=settings.qwen_model,
        qwen_base_url=settings.qwen_base_url,
        advance=True,
    )
    data = extract_json(content)
    if not isinstance(data.get("approved"), bool):
        raise ValueError("quality gate did not return approved boolean")
    issues = _string_list(data.get("issues", []), field="issues")
    language_issues = _actual_findings(
        _string_list(data.get("language_issues", []), field="language_issues")
    )
    blocking_issues = _string_list(data.get("blocking_issues", []), field="blocking_issues")
    fact_checks = data.get("fact_checks", [])
    translations = data.get("translations", [])
    if not isinstance(fact_checks, list) or not isinstance(translations, list):
        raise ValueError("quality gate returned invalid review report")
    deterministic_issues = _deterministic_review_issues(
        fact_checks=fact_checks,
        language_issues=language_issues,
        blocking_issues=blocking_issues,
    )
    report = {
        "fact_checks": fact_checks,
        "language_issues": language_issues,
        "blocking_issues": blocking_issues,
        "translations": translations if translate_sources else [],
    }
    return (
        # Model verdicts frequently mark every omitted detail from a long source
        # as critical. Only concrete, machine-enforced blocking findings stop a
        # draft; omissions remain visible to the editor in the review report.
        not deterministic_issues,
        [*issues, *deterministic_issues],
        report,
        key_alias,
        model,
        usage,
    )
