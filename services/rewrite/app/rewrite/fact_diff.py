"""Deterministic filters 1–3: missing / invented / distorted facts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rewrite_app.rewrite.review_report import filter_result, finding

_CURRENCY = r"(?:\$|€|£|¥|USD|EUR|RUB|USDT)"
_SUFFIX = (
    r"(?:\s*(?:млн|млрд|тыс\.?|million|billion|thousand|k|m|bn|btc|eth|%|pct|процент(?:а|ов)?))"
)
_NUMBER_RE = re.compile(
    rf"(?i)(?<![A-Za-zА-Яа-я0-9])"
    rf"(?:{_CURRENCY}\s*)?"
    rf"(?:\d{{1,3}}(?:[\s,]\d{{3}})+|\d+)"
    rf"(?:[.,]\d+)?"
    rf"{_SUFFIX}?"
)

_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,  # май/мая
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_DATE_RE = re.compile(
    r"(?i)(?:\b(?:в|во)\s+)?"
    r"(?:"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month_name>января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря|january|february|march|april|may|june|"
    r"july|august|september|october|november|december)"
    r"(?:\s+(?P<year1>20\d{2}))?"
    r"|"
    r"(?P<month_only>январе|феврале|марте|апреле|мае|июне|июле|августе|"
    r"сентябре|октябре|ноябре|декабре|january|february|march|april|may|june|"
    r"july|august|september|october|november|december)"
    r"(?:\s+(?P<year2>20\d{2}))?"
    r"|"
    r"(?P<iso>20\d{2}-\d{2}-\d{2})"
    r")"
)

_NAME_EN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_NAME_RU_RE = re.compile(r"\b([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+)\b")
_WHO_FACT_RE = re.compile(r"^-\s*\[who\]\s*(.+)$", re.I | re.M)

_STOP_NAMES = frozenset(
    {
        "The Block",
        "Coin Telegraph",
        "Cointelegraph",
        "United States",
        "New York",
        "Wall Street",
        "White House",
        "Federal Reserve",
        "European Union",
    }
)


@dataclass(frozen=True)
class _NumberHit:
    raw: str
    value: float
    kind: str  # money|crypto|percent|plain


@dataclass(frozen=True)
class _DateHit:
    raw: str
    month: int | None
    day: int | None
    year: int | None
    key: str


def _strip_noise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_number(raw: str) -> _NumberHit | None:
    token = raw.strip()
    if not token:
        return None
    lower = token.lower()
    kind = "plain"
    if re.search(r"[\$€£¥]|usd|eur|rub|usdt|млн|млрд|million|billion", lower):
        kind = "money"
    if re.search(r"\bbtc\b|\beth\b", lower):
        kind = "crypto"
    if "%" in token or "pct" in lower or "процент" in lower:
        kind = "percent"

    multiplier = 1.0
    if re.search(r"млрд|billion|\bbn\b", lower):
        multiplier = 1_000_000_000
    elif re.search(r"млн|million|\bm\b", lower) and not re.search(r"\bbtc\b|\beth\b", lower):
        multiplier = 1_000_000
    elif re.search(r"тыс|thousand|\bk\b", lower):
        multiplier = 1_000

    core = re.sub(r"(?i)^(?:\$|€|£|¥|usd|eur|rub|usdt)\s*", "", token)
    core = re.sub(
        r"(?i)\s*(?:млн|млрд|тыс\.?|million|billion|thousand|k|m|bn|btc|eth|%|pct|"
        r"процент(?:а|ов)?)\s*$",
        "",
        core,
    ).strip()
    # thousand separators vs decimal
    if "," in core and "." in core:
        if core.rfind(",") > core.rfind("."):
            core = core.replace(".", "").replace(",", ".")
        else:
            core = core.replace(",", "")
    elif "," in core:
        parts = core.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            core = parts[0].replace(" ", "") + "." + parts[1]
        else:
            core = core.replace(",", "").replace(" ", "")
    else:
        core = core.replace(" ", "")
        if core.count(".") > 1:
            core = core.replace(".", "")

    try:
        value = float(core) * multiplier
    except ValueError:
        return None
    if value == 0:
        return None
    return _NumberHit(raw=token, value=value, kind=kind)


def extract_numbers(text: str) -> list[_NumberHit]:
    hits: list[_NumberHit] = []
    seen: set[tuple[float, str]] = set()
    for match in _NUMBER_RE.finditer(text or ""):
        parsed = _parse_number(match.group(0))
        if parsed is None:
            continue
        key = (parsed.value, parsed.kind)
        if key in seen:
            continue
        seen.add(key)
        hits.append(parsed)
    return hits


def _month_from_name(name: str) -> int | None:
    lower = name.lower()
    for stem, month in _MONTHS.items():
        if lower.startswith(stem):
            return month
    return None


def extract_dates(text: str) -> list[_DateHit]:
    hits: list[_DateHit] = []
    seen: set[str] = set()
    for match in _DATE_RE.finditer(text or ""):
        raw = _strip_noise(match.group(0))
        if match.group("iso"):
            year_s, month_s, day_s = match.group("iso").split("-")
            hit = _DateHit(
                raw, int(month_s), int(day_s), int(year_s), f"{year_s}-{month_s}-{day_s}"
            )
        else:
            month_name = match.group("month_name") or match.group("month_only") or ""
            month = _month_from_name(month_name)
            day = int(match.group("day")) if match.group("day") else None
            year_s = match.group("year1") or match.group("year2")
            year = int(year_s) if year_s else None
            hit = _DateHit(raw, month, day, year, f"{year or 0}-{month or 0}-{day or 0}")
        if hit.key in seen:
            continue
        seen.add(hit.key)
        hits.append(hit)
    return hits


def extract_names(text: str, facts_text: str = "") -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        cleaned = _strip_noise(name)
        if len(cleaned) < 3 or cleaned in _STOP_NAMES:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(cleaned)

    for match in _WHO_FACT_RE.finditer(facts_text or ""):
        _add(match.group(1))
    for match in _NAME_EN_RE.finditer(text or ""):
        _add(match.group(1))
    for match in _NAME_RU_RE.finditer(text or ""):
        _add(match.group(1))
    return names


def _number_severity(hit: _NumberHit) -> str:
    if hit.kind in {"money", "crypto", "percent"}:
        return "critical"
    if hit.value >= 1000:
        return "critical"
    return "warning"


def _same_significant_digits(a: float, b: float) -> bool:
    if a <= 0 or b <= 0:
        return False
    sa = f"{a:.12g}".replace(".", "").lstrip("0")
    sb = f"{b:.12g}".replace(".", "").lstrip("0")
    if not sa or not sb:
        return False
    prefix = min(4, len(sa), len(sb))
    return sa[:prefix] == sb[:prefix]


def _is_magnitude_distortion(a: float, b: float) -> bool:
    if a <= 0 or b <= 0 or a == b:
        return False
    hi, lo = (a, b) if a > b else (b, a)
    ratio = hi / lo
    log_ratio = math.log10(ratio)
    power = round(log_ratio)
    if power < 1:
        return False
    if abs(log_ratio - power) > 0.08:
        return False
    return _same_significant_digits(a, b)


def _date_close(a: _DateHit, b: _DateHit) -> bool:
    if a.month and b.month and a.month != b.month:
        return False
    if a.day and b.day and a.day != b.day:
        return False
    return True


def _date_exact(a: _DateHit, b: _DateHit) -> bool:
    return a.month == b.month and a.day == b.day and a.year == b.year


def compare_facts(
    *,
    source_text: str,
    rewrite_text: str,
    facts_text: str = "",
) -> dict[str, dict]:
    """Run filters 1–3 and return filter result dicts plus coverage metadata."""
    src_numbers = extract_numbers(source_text)
    rew_numbers = extract_numbers(rewrite_text)
    src_dates = extract_dates(source_text)
    rew_dates = extract_dates(rewrite_text)
    src_names = extract_names(source_text, facts_text)
    rew_names = extract_names(rewrite_text, "")
    rew_names_cf = {n.casefold() for n in rew_names}
    src_names_cf = {n.casefold() for n in src_names}

    missing_findings: list[dict] = []
    invented_findings: list[dict] = []
    distorted_findings: list[dict] = []

    matched_src_number_idxs: set[int] = set()
    matched_rew_number_idxs: set[int] = set()

    # Exact number matches first.
    for i, src in enumerate(src_numbers):
        for j, rew in enumerate(rew_numbers):
            if j in matched_rew_number_idxs:
                continue
            if abs(src.value - rew.value) <= max(1e-9, src.value * 1e-9):
                matched_src_number_idxs.add(i)
                matched_rew_number_idxs.add(j)
                break

    # Magnitude distortions on unmatched pairs.
    for i, src in enumerate(src_numbers):
        if i in matched_src_number_idxs:
            continue
        for j, rew in enumerate(rew_numbers):
            if j in matched_rew_number_idxs:
                continue
            if _is_magnitude_distortion(src.value, rew.value):
                distorted_findings.append(
                    finding(
                        severity="critical",
                        message=f"искажена цифра: «{src.raw}» → «{rew.raw}»",
                        source_span=src.raw,
                        rewrite_span=rew.raw,
                    )
                )
                matched_src_number_idxs.add(i)
                matched_rew_number_idxs.add(j)
                break

    for i, src in enumerate(src_numbers):
        if i in matched_src_number_idxs:
            continue
        missing_findings.append(
            finding(
                severity=_number_severity(src),  # type: ignore[arg-type]
                message=f"пропала цифра: «{src.raw}»",
                source_span=src.raw,
                rewrite_span="",
            )
        )

    for j, rew in enumerate(rew_numbers):
        if j in matched_rew_number_idxs:
            continue
        # invented number — always critical per product brief
        invented_findings.append(
            finding(
                severity="critical",
                message=f"этого нет в источнике: «{rew.raw}»",
                source_span="",
                rewrite_span=rew.raw,
            )
        )

    matched_src_dates: set[int] = set()
    matched_rew_dates: set[int] = set()
    for i, src in enumerate(src_dates):
        for j, rew in enumerate(rew_dates):
            if j in matched_rew_dates:
                continue
            if not _date_close(src, rew):
                continue
            if _date_exact(src, rew):
                matched_src_dates.add(i)
                matched_rew_dates.add(j)
                break
            # same month/day but year added or changed
            if src.year != rew.year:
                distorted_findings.append(
                    finding(
                        severity="critical",
                        message=f"искажена дата: «{src.raw}» → «{rew.raw}»",
                        source_span=src.raw,
                        rewrite_span=rew.raw,
                    )
                )
                matched_src_dates.add(i)
                matched_rew_dates.add(j)
                break

    for i, src in enumerate(src_dates):
        if i in matched_src_dates:
            continue
        missing_findings.append(
            finding(
                severity="critical",
                message=f"пропала дата: «{src.raw}»",
                source_span=src.raw,
            )
        )
    for j, rew in enumerate(rew_dates):
        if j in matched_rew_dates:
            continue
        invented_findings.append(
            finding(
                severity="critical",
                message=f"этого нет в источнике: «{rew.raw}»",
                rewrite_span=rew.raw,
            )
        )

    for name in src_names:
        if name.casefold() in rew_names_cf:
            continue
        # allow last-token match (Elon Musk → Musk)
        tokens = name.split()
        if tokens and tokens[-1].casefold() in {n.casefold() for n in rew_names} | {
            t.casefold() for n in rew_names for t in n.split()
        }:
            # last name present somewhere in rewrite names or as token in rewrite text
            if tokens[-1].casefold() in rewrite_text.casefold():
                continue
        if name.casefold() in rewrite_text.casefold():
            continue
        missing_findings.append(
            finding(
                severity="critical",
                message=f"пропало имя: «{name}»",
                source_span=name,
            )
        )

    for name in rew_names:
        if name.casefold() in src_names_cf:
            continue
        tokens = name.split()
        if name.casefold() in source_text.casefold():
            continue
        if tokens and tokens[-1].casefold() in source_text.casefold():
            continue
        invented_findings.append(
            finding(
                severity="critical",
                message=f"этого нет в источнике: «{name}»",
                rewrite_span=name,
            )
        )

    coverage_base = len(src_numbers) + len(src_dates) + len(src_names)
    missing = filter_result(missing_findings)
    missing["source_entity_count"] = coverage_base
    return {
        "missing": missing,
        "invented": filter_result(invented_findings),
        "distorted": filter_result(distorted_findings),
        "_coverage_base": coverage_base,
    }
