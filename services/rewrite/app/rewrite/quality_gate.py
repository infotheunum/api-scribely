"""Filter 6: LLM semantic review (cause/effect, support, duplicates, quote flip)."""

from __future__ import annotations

import logging

from common.token_usage import TokenUsage
from rewrite_app.rewrite.openrouter_client import extract_json
from rewrite_app.rewrite.review_report import filter_result, finding
from rewrite_app.rewrite.rotation import call_with_rotation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — смысловой редактор рерайта. Фильтры 1–5 уже проверили цифры,
даты, имена, цитаты дословно и запрещённые слова. Твоя задача — только то, что
машина не ловит. Будь консервативен: ложные блоки дорого стоят.

critical в semantic_findings — ТОЛЬКО если:
1) причина и следствие явно перевёрнуты (не просто другая формулировка);
2) смысл прямой цитаты перевёрнут относительно оригинала.

warning (не блокируй approved) — если:
- тезис слабо опирается на оригинал, но не противоречит фактам;
- повтор одной мысли;
- спорная формулировка связи событий без явного переворота;
- стилистическая шероховатость без искажения смысла.

Не дублируй проверки цифр/дат/имён/URL/ID. Не строй полный fact registry.
Не ставь critical из‑за пропуска второстепенной детали, другой структуры абзацев
или нормального журналистского перефраза.

language_issues — только явные ошибки перевода/согласования/ломаный русский.
Неясные термины → editorial_review_flags, не language_issues.
blocking_issues — только инвестсовет, URL/название источника в теле, оценочный
политический контекст.

approved=true, если нет critical semantic_findings, language_issues и
blocking_issues. Warning сам по себе approved не отменяет.

Верни строго JSON:
{"approved": true|false,
 "issues": ["конкретная смысловая проблема"],
 "semantic_findings": [{"severity": "critical|warning", "message": "...",
   "source_span": "фрагмент оригинала или пусто",
   "rewrite_span": "фрагмент рерайта"}],
 "language_issues": ["ошибка перевода/грамматики/англицизм"],
 "editorial_review_flags": ["неясный термин для ручной проверки"],
 "blocking_issues": ["инвестсовет, URL, источник или политическая оценка"]}.
Если ошибок нет — пустые массивы, без фраз «нет ошибок».
Поле translations не возвращай."""

TRANSLATION_SYSTEM_PROMPT = """Ты — переводчик для внутренней редакционной панели.
Переведи каждый переданный исходник на русский полностью и буквально, сохранив
факты, числа, даты, имена, структуру абзацев и прямые цитаты. Не сокращай,
не пересказывай и не добавляй оценки. Верни строго JSON без markdown:
{"translations": [{"title": "точный заголовок исходника", "body_ru": "полный перевод на русский"}]}.
"""


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


def _parse_semantic_findings(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("quality gate returned invalid semantic_findings")
    findings: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("quality gate returned invalid semantic_findings")
        severity = str(item.get("severity") or "warning").strip().lower()
        if severity not in {"critical", "warning"}:
            severity = "warning"
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        findings.append(
            finding(
                severity=severity,  # type: ignore[arg-type]
                message=message,
                source_span=str(item.get("source_span") or ""),
                rewrite_span=str(item.get("rewrite_span") or ""),
            )
        )
    return findings


def _translate_sources_best_effort(
    db, settings, *, sources_text: str
) -> tuple[list[object], TokenUsage]:
    """Keep admin translations without making their long output block draft creation."""
    try:
        content, _, _, usage = call_with_rotation(
            db,
            api_keys=settings.llm_provider_keys(db),
            system_prompt=TRANSLATION_SYSTEM_PROMPT,
            user_prompt=f"ИСХОДНИКИ ДЛЯ ПОЛНОГО ПЕРЕВОДА:\n{sources_text}",
            anthropic_model=settings.anthropic_model,
            openai_model=settings.openai_model,
            qwen_model=settings.qwen_model,
            qwen_base_url=settings.qwen_base_url,
            advance=True,
        )
        translations = extract_json(content).get("translations", [])
        if not isinstance(translations, list):
            raise ValueError("translation pass returned invalid translations")
        return translations, usage
    except Exception as exc:  # Translation is editorial metadata, not a publish gate.
        logger.warning("source translation pass failed without blocking draft: %s", exc)
        return [], TokenUsage(0, 0, 0)


def review_rewrite(
    db,
    settings,
    *,
    sources_text: str,
    required_facts_text: str,
    rewritten_text: str,
    translate_sources: bool,
):
    """Semantic filter 6. ``required_facts_text`` kept for call-site compatibility."""
    del required_facts_text  # Covered by deterministic filters 1–3.
    content, key_alias, model, usage = call_with_rotation(
        db,
        api_keys=settings.llm_provider_keys(db),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            f"ОРИГИНАЛЫ:\n{sources_text}\n\nРЕРАЙТ:\n{rewritten_text}"
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
    editorial_review_flags = _actual_findings(
        _string_list(data.get("editorial_review_flags", []), field="editorial_review_flags")
    )
    blocking_issues = _string_list(data.get("blocking_issues", []), field="blocking_issues")
    semantic_findings = _parse_semantic_findings(data.get("semantic_findings", []))

    # Language / policy lists remain hard blockers (deterministic override of approved).
    for item in language_issues:
        semantic_findings.append(
            finding(severity="critical", message=item, rewrite_span=item)
        )
    for item in blocking_issues:
        semantic_findings.append(
            finding(severity="critical", message=item, rewrite_span=item)
        )

    semantic_filter = filter_result(semantic_findings)
    deterministic_blockers = [
        f["message"] for f in semantic_findings if f.get("severity") == "critical"
    ]

    translations: list[object] = []
    if translate_sources and not deterministic_blockers:
        translations, translation_usage = _translate_sources_best_effort(
            db, settings, sources_text=sources_text
        )
        usage += translation_usage

    report = {
        "fact_checks": [],
        "required_fact_checks": [],
        "language_issues": language_issues,
        "editorial_review_flags": editorial_review_flags,
        "blocking_issues": blocking_issues,
        "translations": translations if translate_sources else [],
        "filters": {"semantic": semantic_filter},
    }
    return (
        not deterministic_blockers,
        [*issues, *deterministic_blockers],
        report,
        key_alias,
        model,
        usage,
    )
