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
    "{phrase, category} objects. Categories: investment, political, "
    "evaluation, bad_translation. Matches outside quotes only. "
    "Investment → critical; evaluation/political → warning."
)

# Seed inventory from style guide + editorial brief. Runtime SoT is AppSetting
# merged with these defaults (DB can add/override; code adds never drop).
DEFAULT_BANNED_PHRASES: list[dict[str, str]] = [
    # investment advice tone → critical findings
    {"phrase": "следите", "category": "investment"},
    {"phrase": "требует внимания", "category": "investment"},
    {"phrase": "может предвещать", "category": "investment"},
    {"phrase": "buy now", "category": "investment"},
    {"phrase": "стоит купить", "category": "investment"},
    {"phrase": "рекомендуем купить", "category": "investment"},
    {"phrase": "не рекомендует покупать", "category": "investment"},
    {"phrase": "хорошая возможность для покупки", "category": "investment"},
    {"phrase": "возможность для покупки", "category": "investment"},
    {"phrase": "потенциальная точка входа", "category": "investment"},
    {"phrase": "точка входа", "category": "investment"},
    {"phrase": "потенциал роста", "category": "investment"},
    {"phrase": "возможности для инвестирования", "category": "investment"},
    {"phrase": "новые возможности для инвестирования", "category": "investment"},
    {"phrase": "путь для инвестирования", "category": "investment"},
    {"phrase": "главным катализатором", "category": "investment"},
    {"phrase": "стать катализатором", "category": "investment"},
    {"phrase": "добиться прорыва", "category": "investment"},
    {"phrase": "гарантировать большую ликвидность", "category": "investment"},
    {"phrase": "хорошая возможность", "category": "investment"},
    {"phrase": "инвестиционная возможность", "category": "investment"},
    {"phrase": "рекомендуем к покупке", "category": "investment"},
    {"phrase": "время покупать", "category": "investment"},
    {"phrase": "не упустите возможность", "category": "investment"},
    {"phrase": "выгодная покупка", "category": "investment"},
    {"phrase": "сигнал к покупке", "category": "investment"},
    {"phrase": "сигнал на покупку", "category": "investment"},
    {"phrase": "пора покупать", "category": "investment"},
    {"phrase": "стоит обратить внимание инвесторам", "category": "investment"},
    {"phrase": "для инвесторов это", "category": "investment"},
    {"phrase": "рекомендуется", "category": "investment"},
    # evaluative fluff not grounded in source (warning)
    {"phrase": "значительный шаг", "category": "evaluation"},
    {"phrase": "впечатляющий рост", "category": "evaluation"},
    {"phrase": "открывает новые горизонты", "category": "evaluation"},
    {"phrase": "усиливает подозрения", "category": "evaluation"},
    # political / climate padding not grounded in source
    {"phrase": "изменение климата", "category": "political"},
    {"phrase": "глобального изменения климата", "category": "political"},
    {"phrase": "глобальное изменение климата", "category": "political"},
    {"phrase": "климатический кризис", "category": "political"},
    {"phrase": "администрация байдена", "category": "political"},
    {"phrase": "администрация трампа", "category": "political"},
    {"phrase": "геополитическ", "category": "political"},
    {"phrase": "на фоне геополитики", "category": "political"},
    {"phrase": "политическое давление", "category": "political"},
    {"phrase": "санкционное давление", "category": "political"},
    # bad translation / glossary misses
    {"phrase": "лендинг", "category": "bad_translation"},
    {"phrase": "кредитный etf", "category": "bad_translation"},
    {"phrase": "кредитный ETF", "category": "bad_translation"},
]

# Critical categories block advisory/strict gates; political stays warning.
_CRITICAL_CATEGORIES = frozenset({"investment"})


def parse_banned_phrases(raw: Any) -> list[dict[str, str]]:
    """Parse AppSetting JSON; empty/invalid → code defaults only."""
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


def merge_banned_phrases(db_phrases: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Code defaults ∪ DB list. DB wins on same phrase (category/override)."""
    merged: dict[str, dict[str, str]] = {
        item["phrase"].casefold(): dict(item) for item in DEFAULT_BANNED_PHRASES
    }
    for item in db_phrases or []:
        phrase = str(item.get("phrase") or "").strip()
        if not phrase:
            continue
        category = str(item.get("category") or "other").strip() or "other"
        merged[phrase.casefold()] = {"phrase": phrase, "category": category}
    return list(merged.values())


def get_banned_phrases(db: Session | None) -> list[dict[str, str]]:
    if db is None:
        return [dict(item) for item in DEFAULT_BANNED_PHRASES]
    raw = get_setting(db, BANNED_PHRASES_KEY, None)
    if raw is None or raw == "":
        return [dict(item) for item in DEFAULT_BANNED_PHRASES]
    return merge_banned_phrases(parse_banned_phrases(raw))


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
    # Prefix stems (геополитическ…) match morphological endings.
    escaped = re.escape(phrase)
    if phrase.endswith(("ск", "еск")):
        return re.compile(rf"(?iu)(?<!\w){escaped}\w*")
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
            sev = "critical" if category in _CRITICAL_CATEGORIES else "warning"
            findings.append(
                finding(
                    severity=sev,  # type: ignore[arg-type]
                    message=f"плохая формулировка ({category}): «{match.group(0)}»",
                    rewrite_span=match.group(0),
                    category=category,
                )
            )
    return filter_result(findings)
