from __future__ import annotations

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import call_with_rotation

SYSTEM_PROMPT = """Ты — строгий фактчекер и литературный редактор. Сверь ОРИГИНАЛЫ и
РЕРАЙТ. Одобри только если ключевые факты, имена, цифры и даты переданы верно;
нет выдуманных фактов, инвестиционных рекомендаций, URL/названий источников,
оценочного политического контекста, ошибок перевода, грамматики и неуместных
англицизмов в русской версии.

Ниже в запросе будет список «ОБЯЗАТЕЛЬНЫЕ ФАКТЫ». Это фактический реестр,
извлеченный до рерайта: главная суть, имена, даты и точные числа. Рерайт
обязан сохранить КАЖДЫЙ такой факт. Обычные детали источника можно отметить
как упущенные в fact_checks, но отсутствие хотя бы одного обязательного факта
не допускается.
Никогда не ставь approved=true, если status «искажён» или «добавлено», при
любой реальной ошибке перевода, орфографии, грамматики или при англицизме,
который не является официальным названием, именем, тикером или аббревиатурой.
Также не одобряй инвестиционные рекомендации, URL/несогласованную атрибуцию и
оценочный политический контекст. Не придирайся к синонимам.

Верни строго JSON:
{"approved": true|false, "issues": ["конкретная проблема и точная правка"],
 "language_issues": ["ошибка перевода, грамматики или неуместный англицизм"],
 "blocking_issues": ["инвестиционная рекомендация, URL, источник или политическая оценка"],
 "required_fact_checks": [{"required_fact": "дословный пункт из ОБЯЗАТЕЛЬНЫХ ФАКТОВ", "status": "сохранен|упущен|искажен", "rewrite_evidence": "фрагмент рерайта"}],
 "fact_checks": [{"fact": "ключевой факт из оригинала", "status": "совпадает|упущен|искажён|добавлено", "severity": "critical|secondary", "rewrite_evidence": "как передано в рерайте"}],
 "translations": [{"title": "точный заголовок исходника", "body_ru": "полный перевод на русский"}]}.
Если ошибок нет, language_issues и blocking_issues должны быть пустыми массивами:
не пиши в них фразы «нет ошибок» или другие пояснения. Поле translations
заполняй только когда в запросе явно включён перевод. required_fact_checks
должен содержать РОВНО один элемент для каждого пункта из ОБЯЗАТЕЛЬНЫХ ФАКТОВ;
при отсутствии такого списка верни пустой массив."""

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


def _required_fact_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("- ["))


def _deterministic_review_issues(
    *,
    fact_checks: list[object],
    required_fact_checks: list[object],
    language_issues: list[str],
    blocking_issues: list[str],
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
    for item in required_fact_checks:
        if not isinstance(item, dict):
            raise ValueError("quality gate returned invalid required_fact_checks")
        status = _normalized_status(item.get("status"))
        required_fact = str(item.get("required_fact") or "обязательный факт").strip()
        if status in {"упущен", "искажен"}:
            blocked.append(f"{required_fact}: обязательный факт {status}")
    return blocked


def review_rewrite(
    db,
    settings,
    *,
    sources_text: str,
    required_facts_text: str,
    rewritten_text: str,
    translate_sources: bool,
):
    content, key_alias, model, usage = call_with_rotation(
        db,
        api_keys=settings.llm_provider_keys(),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            f"ОРИГИНАЛЫ:\n{sources_text}\n\nОБЯЗАТЕЛЬНЫЕ ФАКТЫ:\n{required_facts_text}\n\n"
            f"РЕРАЙТ:\n{rewritten_text}\n\n"
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
    required_fact_checks = data.get("required_fact_checks", [])
    translations = data.get("translations", [])
    if (
        not isinstance(fact_checks, list)
        or not isinstance(required_fact_checks, list)
        or not isinstance(translations, list)
    ):
        raise ValueError("quality gate returned invalid review report")
    expected_required_facts = _required_fact_count(required_facts_text)
    if len(required_fact_checks) != expected_required_facts:
        raise ValueError(
            "quality gate did not check every required fact "
            f"({len(required_fact_checks)}/{expected_required_facts})"
        )
    deterministic_issues = _deterministic_review_issues(
        fact_checks=fact_checks,
        required_fact_checks=required_fact_checks,
        language_issues=language_issues,
        blocking_issues=blocking_issues,
    )
    report = {
        "fact_checks": fact_checks,
        "required_fact_checks": required_fact_checks,
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
