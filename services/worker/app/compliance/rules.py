from __future__ import annotations

import re

from db.enums import SourceTier
from db.models import Draft, NewsCluster

# Coarse keyword safety net for Редакционная_Политика_UNUM §11.4 — a
# rule-based backstop underneath the LLM's own judgment, not a
# substitute for real content moderation. Only categories with a
# tractable keyword/structural signal are covered here:
# violence/extremism phrasing, explicit ("buy now") investment advice,
# and structural PII mentions (SSN/passport numbers). Discrimination and
# adult-content detection are deliberately NOT keyword-matched here — a
# naive keyword list for either is either useless (too narrow to catch
# anything real) or actively harmful to maintain (a slur list checked
# into source control); both stay the LLM's own judgment call plus human
# review (Фаза 6), same as §11.4's catch-all "нарушает применимое
# законодательство" is inherently a human call, not a regex.
FORBIDDEN_PATTERNS: dict[str, list[str]] = {
    "violence_extremism": [
        r"\bincite(s|d)? violence\b",
        r"\bterrorist attack\b",
        r"\bпризыв(ы)? к насилию\b",
        r"\bтеррористическ",
    ],
    "explicit_investment_advice": [
        r"\bbuy now\b",
        r"\binvest now\b",
        r"\bguaranteed (profit|return)s?\b",
        r"\bthis is financial advice\b",
        r"\bпокупайте (сейчас|немедленно)\b",
        r"\bгарантированн(ая|ый) прибыл",
    ],
    "pii_exposure": [
        r"\bsocial security number\b",
        r"\bpassport number\b",
        r"\bномер паспорта\b",
    ],
}

# Softer signal than FORBIDDEN_PATTERNS' explicit_investment_advice —
# hedged/optimistic price language that should carry a disclaimer (§2.5
# редполитики) without blocking the draft outright. This is a backstop:
# RewriteCluster's own disclaimer_flag (Фаза 4, LLM self-assessment) is
# the primary signal.
DISCLAIMER_TRIGGER_PATTERNS = [
    r"\bcould (see|reach|hit) \$",
    r"\bpotential upside\b",
    r"\bmight (surge|rally|soar)\b",
    r"\bможет (вырасти|достичь)\b",
]


def check_forbidden_content(text: str) -> list[str]:
    """Returns the §11.4 categories whose patterns matched, or [] if
    clean. Case-insensitive; matches against the combined EN+RU text."""
    lowered = text.lower()
    hits = []
    for category, patterns in FORBIDDEN_PATTERNS.items():
        if any(re.search(p, lowered) for p in patterns):
            hits.append(category)
    return hits


def matches_disclaimer_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in DISCLAIMER_TRIGGER_PATTERNS)


def has_attribution(draft: Draft) -> bool:
    return bool(draft.attribution_urls)


def is_press_release_by_tier(cluster: NewsCluster) -> bool:
    """Rule-based backstop for RewriteCluster's own press_release_flag
    (ТЗ §6.3, §4.21): Уровень 6 = пресс-релиз wire-сервисы (реестр П7)
    — any source in the cluster at that tier makes the material a press
    release regardless of what the LLM concluded on its own."""
    return any(item.source.tier == SourceTier.TIER_6 for item in cluster.raw_items)
