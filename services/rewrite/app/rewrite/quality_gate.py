from __future__ import annotations

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.rotation import call_with_rotation

SYSTEM_PROMPT = """Ты — строгий фактчекер и литературный редактор. Сверь ОРИГИНАЛЫ и
РЕРАЙТ. Одобри только если ключевые факты, имена, цифры и даты переданы верно;
нет выдуманных фактов, инвестиционных рекомендаций, URL/названий источников,
оценочного политического контекста, ошибок перевода, грамматики и неуместных
англицизмов в русской версии.

Для каждого fact_checks укажи severity: critical, если упущение или ошибка
меняет смысл новости, касается главного события, цифры, даты, имени, должности
или причинно-следственной связи; secondary — только для второстепенной детали.
Никогда не ставь approved=true, если status «искажён» или «добавлено», либо
если status «упущен» и severity=critical. Никогда не ставь approved=true при
любой реальной ошибке перевода, орфографии, грамматики или при англицизме,
который не является официальным названием, именем, тикером или аббревиатурой.
Не придирайся к синонимам и допустимым второстепенным упущениям.

Верни строго JSON:
{"approved": true|false, "issues": ["конкретная проблема и точная правка"],
 "language_issues": ["ошибка перевода, грамматики или неуместный англицизм"],
 "fact_checks": [{"fact": "ключевой факт из оригинала", "status": "совпадает|упущен|искажён|добавлено", "severity": "critical|secondary", "rewrite_evidence": "как передано в рерайте"}],
 "translations": [{"title": "точный заголовок исходника", "body_ru": "полный перевод на русский"}]}.
Поле translations заполняй только когда в запросе явно включён перевод."""

_BLOCKING_FACT_STATUSES = {"искажен", "добавлено"}


def _normalized_status(value: object) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"quality gate returned invalid {field}")
    return [item.strip() for item in value if item.strip()]


def _deterministic_review_issues(
    *, fact_checks: list[object], language_issues: list[str]
) -> list[str]:
    """Do not let an internally inconsistent LLM verdict publish bad copy."""
    blocked = list(language_issues)
    for item in fact_checks:
        if not isinstance(item, dict):
            raise ValueError("quality gate returned invalid fact_checks")
        status = _normalized_status(item.get("status"))
        # A missing severity is not a safe declaration that an omission is minor.
        severity = str(item.get("severity") or "critical").strip().lower()
        fact = str(item.get("fact") or "ключевой факт").strip()
        if status in _BLOCKING_FACT_STATUSES:
            blocked.append(f"{fact}: статус «{item.get('status')}»")
        elif status == "упущен" and severity == "critical":
            blocked.append(f"{fact}: критически упущен")
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
    language_issues = _string_list(data.get("language_issues", []), field="language_issues")
    fact_checks = data.get("fact_checks", [])
    translations = data.get("translations", [])
    if not isinstance(fact_checks, list) or not isinstance(translations, list):
        raise ValueError("quality gate returned invalid review report")
    deterministic_issues = _deterministic_review_issues(
        fact_checks=fact_checks, language_issues=language_issues
    )
    report = {
        "fact_checks": fact_checks,
        "language_issues": language_issues,
        "translations": translations if translate_sources else [],
    }
    return (
        data["approved"] and not deterministic_issues,
        [*issues, *deterministic_issues],
        report,
        key_alias,
        model,
        usage,
    )
