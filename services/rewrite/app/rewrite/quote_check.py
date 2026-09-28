"""Filter 4: quote fidelity, attribution, and title inflation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from rewrite_app.rewrite.review_report import filter_result, finding

_QUOTE_RE = re.compile(
    r"«([^»]{3,})»|"
    r"\"([^\"]{3,})\"|"
    r"“([^”]{3,})”|"
    r"'([^']{3,})'"
)

_ATTR_BEFORE = re.compile(
    r"(?is)([A-ZА-ЯЁ][\w.А-Яа-яЁё\- ]{1,60}?)\s*"
    r"(?:сказал[аи]?|заявил[аи]?|отметил[аи]?|подчеркн\w+|рассказал[аи]?|"
    r"пояснил[аи]?|написал[аи]?|считает|полагает|уточнил[аи]?|"
    r"said|says|stated|noted|told|wrote|according to)\s*[:,\s]*$"
)
_ATTR_AFTER = re.compile(
    r"(?is)^\s*[,:—–-]\s*(?:сказал[аи]?|заявил[аи]?|отметил[аи]?|"
    r"said|says|stated|noted)?\s*"
    r"([A-ZА-ЯЁ][\w.А-Яа-яЁё\- ]{1,60})"
)
_TITLE_RE = re.compile(
    r"(?i)\b("
    r"генеральн\w+\s+директор\w*|ceo|chief executive|"
    r"основател\w+|founder|председатель\w*|chairman|"
    r"директор\w+\s+по\s+\w+|president|президент\w*"
    r")\b"
)

_FUZZY_DISTORTED = 0.72
_FUZZY_OK = 0.92


@dataclass(frozen=True)
class QuoteHit:
    text: str
    start: int
    end: int


def extract_quotes(text: str) -> list[QuoteHit]:
    hits: list[QuoteHit] = []
    for match in _QUOTE_RE.finditer(text or ""):
        body = next((g for g in match.groups() if g), "")
        body = body.strip()
        if not body:
            continue
        hits.append(QuoteHit(text=body, start=match.start(), end=match.end()))
    return hits


def quote_spans(text: str) -> list[tuple[int, int]]:
    return [(q.start, q.end) for q in extract_quotes(text)]


def _inside_any(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _best_ratio(needle: str, haystack: str) -> float:
    needle_n = " ".join(needle.lower().split())
    hay_n = " ".join(haystack.lower().split())
    if not needle_n:
        return 0.0
    if needle_n in hay_n:
        return 1.0
    # windowed comparison against source sentences / chunks
    best = SequenceMatcher(None, needle_n, hay_n).ratio()
    window = max(len(needle_n) + 40, int(len(needle_n) * 1.3))
    step = max(20, window // 4)
    for i in range(0, max(1, len(hay_n) - window + 1), step):
        chunk = hay_n[i : i + window]
        best = max(best, SequenceMatcher(None, needle_n, chunk).ratio())
    return best


def _has_attribution(text: str, quote: QuoteHit) -> bool:
    before = text[max(0, quote.start - 120) : quote.start]
    after = text[quote.end : min(len(text), quote.end + 120)]
    if _ATTR_BEFORE.search(before):
        return True
    if _ATTR_AFTER.search(after):
        return True
    # dash attribution: — Name or - Name right after
    if re.match(r"\s*[—–-]\s*[A-ZА-ЯЁ]", after):
        return True
    return False


def _title_inflation(source_text: str, rewrite_text: str, quote: QuoteHit) -> str | None:
    window = rewrite_text[max(0, quote.start - 100) : min(len(rewrite_text), quote.end + 100)]
    titles = _TITLE_RE.findall(window)
    if not titles:
        return None
    for title in titles:
        if title.casefold() in source_text.casefold():
            continue
        return title
    return None


def check_quotes(*, source_text: str, rewrite_text: str) -> dict:
    findings: list[dict] = []
    for quote in extract_quotes(rewrite_text):
        ratio = _best_ratio(quote.text, source_text)
        if ratio >= _FUZZY_OK:
            status_msg = None
        elif ratio >= _FUZZY_DISTORTED:
            findings.append(
                finding(
                    severity="critical",
                    message="цитата искажена",
                    source_span="",
                    rewrite_span=quote.text,
                )
            )
            status_msg = "distorted"
        else:
            findings.append(
                finding(
                    severity="critical",
                    message="цитата придумана",
                    source_span="",
                    rewrite_span=quote.text,
                )
            )
            status_msg = "invented"

        if status_msg != "invented" and not _has_attribution(rewrite_text, quote):
            findings.append(
                finding(
                    severity="warning",
                    message="нет автора у цитаты",
                    rewrite_span=quote.text,
                )
            )

        inflated = _title_inflation(source_text, rewrite_text, quote)
        if inflated:
            findings.append(
                finding(
                    severity="warning",
                    message=f"должность не подтверждена источником: «{inflated}»",
                    rewrite_span=quote.text,
                )
            )

    return filter_result(findings)
