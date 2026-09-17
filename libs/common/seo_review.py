from __future__ import annotations

import re
from typing import Any


_NUMBER = re.compile(r"(?<![\w])(?:[$€₽£])?\d+(?:[.,]\d+)?(?:\s?(?:%|млрд|млн|тыс\.?)?)")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")
_STOP_WORDS = {
    "этот", "этого", "этой", "будет", "могут", "может", "года", "год", "после",
    "из-за", "для", "среди", "между", "about", "with", "from", "that", "will",
}
_RU_KNOWN_TYPOS = {
    "приоритизерует": "приоритизирует",
    "e thereuem": "Ethereum",
}


def _issue(field: str, severity: str, rule: str, evidence: str) -> dict[str, str]:
    return {"field": field, "severity": severity, "rule": rule, "evidence": evidence}


def _terms(value: str) -> set[str]:
    return {
        word.lower().replace("ё", "е")
        for word in _WORD.findall(value)
        if word.lower().replace("ё", "е") not in _STOP_WORDS
    }


def _unsupported_numbers(value: str, body: str) -> list[str]:
    body_normalized = body.replace(" ", "")
    return [
        token
        for token in _NUMBER.findall(value)
        if token.replace(" ", "") not in body_normalized
    ]


def review_seo_pack(
    *, locale: str, h1: str, body: str, seo_title: str | None,
    seo_description: str | None, focus_keyphrase: str | None,
) -> dict[str, Any]:
    """Deterministic editorial diagnostics for generated or edited metadata.

    It intentionally warns, rather than blocks, on weak semantic overlap: an
    editor may write a valid synonym-rich SERP title. Facts, visible language
    mistakes and malformed punctuation are blockers because they are concrete.
    """
    title = (seo_title or "").strip()
    description = (seo_description or "").strip()
    keyphrase = (focus_keyphrase or "").strip()
    issues: list[dict[str, str]] = []
    lengths = {"seo_title": len(title), "seo_description": len(description)}

    # A locale can be disabled for a deployment. Empty fields in that locale
    # are intentional and must not make an otherwise valid draft unpublishable.
    if not (h1.strip() or body.strip()):
        return {"locale": locale, "lengths": lengths, "issues": issues}

    if not title:
        issues.append(_issue("seo_title", "blocking", "required", "SEO title не заполнен."))
    elif not 50 <= len(title) <= 70:
        issues.append(_issue("seo_title", "warning", "length", "Рекомендуемая длина: 50–70 символов."))
    if not description:
        issues.append(_issue("seo_description", "blocking", "required", "SEO description не заполнен."))
    elif not 140 <= len(description) <= 160:
        issues.append(_issue("seo_description", "warning", "length", "Рекомендуемая длина: 140–160 символов."))

    metadata = " ".join((title, description, keyphrase))
    for token in _unsupported_numbers(metadata, body):
        issues.append(_issue("seo", "blocking", "source-grounding", f"Число «{token}» отсутствует в тексте статьи."))
    if locale == "ru":
        lowered = metadata.lower()
        for typo, correction in _RU_KNOWN_TYPOS.items():
            if typo in lowered:
                issues.append(_issue("seo", "blocking", "spelling", f"«{typo}» следует исправить на «{correction}»."))
        if re.search(r"\bтем не менее,", lowered):
            issues.append(_issue("seo_description", "blocking", "punctuation", "После «тем не менее» запятая не ставится без отдельного грамматического основания."))

    article_terms = _terms(f"{h1} {body}")
    title_terms = _terms(title)
    if title and title_terms and not article_terms.intersection(title_terms):
        issues.append(_issue("seo_title", "warning", "h1-alignment", "SEO title не содержит общих значимых слов с H1 или текстом; проверьте сущность и событие."))
    if keyphrase and not _terms(keyphrase).intersection(article_terms):
        issues.append(_issue("focus_keyphrase", "warning", "source-grounding", "Фокусная фраза не найдена в H1 или тексте статьи."))
    return {"locale": locale, "lengths": lengths, "issues": issues}


def review_draft_seo(**fields: str | None) -> dict[str, Any]:
    return {
        "ru": review_seo_pack(
            locale="ru", h1=fields.get("title_ru") or "", body=fields.get("body_ru") or "",
            seo_title=fields.get("seo_title_ru"), seo_description=fields.get("seo_description_ru"),
            focus_keyphrase=fields.get("focus_keyphrase_ru"),
        ),
        "en": review_seo_pack(
            locale="en", h1=fields.get("title_en") or "", body=fields.get("body_en") or "",
            seo_title=fields.get("seo_title_en"), seo_description=fields.get("seo_description_en"),
            focus_keyphrase=fields.get("focus_keyphrase_en"),
        ),
    }


def seo_blocking_issues(report: dict[str, Any] | None) -> list[dict[str, str]]:
    return [
        issue for language in (report or {}).values() if isinstance(language, dict)
        for issue in language.get("issues", []) if isinstance(issue, dict) and issue.get("severity") == "blocking"
    ]
