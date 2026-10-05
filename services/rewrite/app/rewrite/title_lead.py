"""Filter: announcement title must not duplicate the lead sentence."""

from __future__ import annotations

import re

from common.rewrite_body_format import split_paragraphs
from rewrite_app.rewrite.review_report import filter_result, finding

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[«»\"'`„“”‚‘’.,!?;:()\[\]{}…—–-]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _normalize(text: str) -> str:
    lowered = (text or "").casefold()
    lowered = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", lowered).strip()


def _first_sentence(paragraph: str) -> str:
    parts = [p.strip() for p in _SENTENCE_END.split(paragraph or "") if p.strip()]
    return parts[0] if parts else (paragraph or "").strip()


def _token_set(text: str) -> set[str]:
    return {tok for tok in _normalize(text).split(" ") if tok}


def _overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / max(len(a), 1)


def check_title_lead(*, title: str, body: str, locale: str = "") -> dict:
    """Warn when title ≈ first sentence / first paragraph of body."""
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return filter_result([])

    paragraphs = split_paragraphs(body)
    lead_para = paragraphs[0] if paragraphs else body
    lead_sentence = _first_sentence(lead_para)

    title_n = _normalize(title)
    lead_n = _normalize(lead_sentence)
    para_n = _normalize(lead_para)
    findings: list[dict] = []
    label = f" ({locale})" if locale else ""

    if title_n and (title_n == lead_n or title_n == para_n):
        findings.append(
            finding(
                severity="warning",
                message=(
                    f"заголовок анонса совпадает с первым предложением{label}: "
                    "лид должен добавить цифру/контекст, а не повторять анонс"
                ),
                rewrite_span=title[:120],
                category="title_lead",
            )
        )
        return filter_result(findings)

    title_tokens = _token_set(title)
    lead_tokens = _token_set(lead_sentence)
    # High lexical overlap + short title fully covered by lead → duplicate.
    if len(title_tokens) >= 3 and title_tokens <= lead_tokens:
        findings.append(
            finding(
                severity="warning",
                message=(
                    f"первое предложение почти дословно повторяет заголовок анонса{label}: "
                    "добавь цифру или контекст, которого нет в анонсе"
                ),
                rewrite_span=lead_sentence[:160],
                category="title_lead",
            )
        )
        return filter_result(findings)

    if _overlap_ratio(title_tokens, lead_tokens) >= 0.85 and len(title_tokens) >= 4:
        findings.append(
            finding(
                severity="warning",
                message=(
                    f"заголовок и лид слишком похожи{label}: анонс — «что случилось», "
                    "первое предложение — «почему важно» + цифра"
                ),
                rewrite_span=lead_sentence[:160],
                category="title_lead",
            )
        )
    return filter_result(findings)


def check_title_lead_pairs(pairs: list[tuple[str, str, str]]) -> dict:
    """Merge findings for (locale, title, body) pairs."""
    findings: list[dict] = []
    for locale, title, body in pairs:
        part = check_title_lead(title=title, body=body, locale=locale)
        findings.extend(part.get("findings") or [])
    return filter_result(findings)
