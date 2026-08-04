from __future__ import annotations

import re

# Topics that get a stronger auto-hold than the regular compliance flags
# (ТЗ §4.6, §4.20, редполитика §11.4/§2.5) — sanctions, crime, death,
# hacks/security incidents. EN+RU keyword sets, same pattern as
# worker/app/filter/topics.py.
SENSITIVE_KEYWORDS: dict[str, list[str]] = {
    "sanctions": [
        r"\bsanction",
        r"\bofac\b",
        r"\bblacklist(ed)?\b",
        r"санкци",
        r"чёрн(ый|ого) список",
        r"черн(ый|ого) список",
    ],
    "crime": [
        r"\bfraud\b",
        r"\bscam\b",
        r"\bmoney laundering\b",
        r"\bindictment\b",
        r"\barrest(ed)?\b",
        r"мошенничеств",
        r"отмыван(ие|ия) денег",
        r"арестован",
    ],
    "death": [
        r"\bdied\b",
        r"\bdeath\b",
        r"\bkilled\b",
        r"\bfatal(ity|ities)?\b",
        r"погиб",
        r"умер",
        r"смерт",
    ],
    "hack": [
        r"\bhack(ed|er)?\b",
        r"\bexploit(ed)?\b",
        r"\bbreach(ed)?\b",
        r"\bstolen funds\b",
        r"взлом",
        r"эксплойт",
        r"хакер",
        r"украден",
    ],
}


def classify_sensitive(text: str) -> list[str]:
    """Returns the matched sensitive categories, or [] if none. A draft
    can match more than one (e.g. a hack that also involves an arrest)."""
    lowered = text.lower()
    matched = []
    for category, patterns in SENSITIVE_KEYWORDS.items():
        if any(re.search(p, lowered) for p in patterns):
            matched.append(category)
    return matched
