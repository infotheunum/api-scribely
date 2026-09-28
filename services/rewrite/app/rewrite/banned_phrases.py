"""Filter 5: banned / style-policy phrases (AppSetting-backed)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from db.app_settings import get_setting, set_setting
from rewrite_app.rewrite.quote_check import quote_spans
from rewrite_app.rewrite.review_report import filter_result, finding
from sqlalchemy.orm import Session

BANNED_PHRASES_KEY = "compliance.banned_phrases"
BANNED_PHRASES_DESCRIPTION = (
    "Phrase blacklist for rewrite filter 5: JSON array of "
    '{phrase, category} objects. Categories: investment, evaluation, '
    "forecast, bureaucracy, bad_translation. Matches outside quotes only."
)

# Seed inventory from style guide + editorial brief. Runtime SoT is AppSetting.
DEFAULT_BANNED_PHRASES: list[dict[str, str]] = [
    # investment advice tone
    {"phrase": "следите", "category": "investment"},
    {"phrase": "требует внимания", "category": "investment"},
    {"phrase": "может предвещать", "category": "investment"},
    {"phrase": "buy now", "category": "investment"},
    {"phrase": "стоит купить", "category": "investment"},
    # evaluative intensifiers
    {"phrase": "важный", "category": "evaluation"},
    {"phrase": "важная", "category": "evaluation"},
    {"phrase": "важное", "category": "evaluation"},
    {"phrase": "значительный", "category": "evaluation"},
    {"phrase": "значительная", "category": "evaluation"},
    {"phrase": "впечатляющий", "category": "evaluation"},
    {"phrase": "впечатляющая", "category": "evaluation"},
    {"phrase": "колоссальный", "category": "evaluation"},
    {"phrase": "беспрецедентный", "category": "evaluation"},
    {"phrase": "ошеломляющий", "category": "evaluation"},
    {"phrase": "поразительный", "category": "evaluation"},
    # forecasts
    {"phrase": "может привести", "category": "forecast"},
    {"phrase": "ожидается", "category": "forecast"},
    {"phrase": "эксперты ожидают", "category": "forecast"},
    # bureaucracy / AI clichés
    {"phrase": "в рамках", "category": "bureaucracy"},
    {"phrase": "данный", "category": "bureaucracy"},
    {"phrase": "данная", "category": "bureaucracy"},
    {"phrase": "данное", "category": "bureaucracy"},
    {"phrase": "таким образом", "category": "bureaucracy"},
    {"phrase": "имеет место быть", "category": "bureaucracy"},
    {"phrase": "на сегодняшний день", "category": "bureaucracy"},
    {"phrase": "в настоящее время", "category": "bureaucracy"},
    {"phrase": "следует отметить", "category": "bureaucracy"},
    {"phrase": "важно отметить", "category": "bureaucracy"},
    {"phrase": "стоит подчеркнуть", "category": "bureaucracy"},
    {"phrase": "нельзя не сказать", "category": "bureaucracy"},
    {"phrase": "подводя итог", "category": "bureaucracy"},
    {"phrase": "в заключение", "category": "bureaucracy"},
    # bad translation / glossary misses
    {"phrase": "лендинг", "category": "bad_translation"},
    {"phrase": "кредитный etf", "category": "bad_translation"},
    {"phrase": "кредитный ETF", "category": "bad_translation"},
]


def parse_banned_phrases(raw: Any) -> list[dict[str, str]]:
    if raw is None or raw == "":
        return [dict(item) for item in DEFAULT_BANNED_PHRASES]
    if not isinstance(raw, list):
        return [dict(item) for item in DEFAULT_BANNED_PHRASES]
    parsed: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            parsed.append({"phrase": item.strip(), "category": "other"})
            continue
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase") or "").strip()
        if not phrase:
            continue
        category = str(item.get("category") or "other").strip() or "other"
        parsed.append({"phrase": phrase, "category": category})
    return parsed or [dict(item) for item in DEFAULT_BANNED_PHRASES]


def get_banned_phrases(db: Session | None) -> list[dict[str, str]]:
    if db is None:
        return [dict(item) for item in DEFAULT_BANNED_PHRASES]
    return parse_banned_phrases(get_setting(db, BANNED_PHRASES_KEY, None))


def set_banned_phrases(
    db: Session,
    phrases: list[dict[str, str]] | list[str],
    *,
    updated_by: uuid.UUID | None = None,
) -> list[dict[str, str]]:
    normalized = parse_banned_phrases(phrases)
    set_setting(
        db,
        BANNED_PHRASES_KEY,
        normalized,
        description=BANNED_PHRASES_DESCRIPTION,
        updated_by=updated_by,
    )
    return normalized


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Word-ish boundaries so «данный» does not fire inside longer tokens.
    escaped = re.escape(phrase)
    return re.compile(rf"(?iu)(?<!\w){escaped}(?!\w)")


def find_banned_phrases(
    text: str,
    phrases: list[dict[str, str]] | None = None,
) -> dict:
    catalog = phrases if phrases is not None else DEFAULT_BANNED_PHRASES
    spans = quote_spans(text)
    findings: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for item in catalog:
        phrase = item["phrase"]
        category = item.get("category") or "other"
        pattern = _phrase_pattern(phrase)
        for match in pattern.finditer(text or ""):
            if any(start <= match.start() < end for start, end in spans):
                continue
            key = (phrase.casefold(), match.start())
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                finding(
                    severity="warning",
                    message=f"плохая формулировка ({category}): «{match.group(0)}»",
                    rewrite_span=match.group(0),
                    category=category,
                )
            )
    return filter_result(findings)
