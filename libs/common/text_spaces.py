"""Normalize typographic / Unicode spaces in rewrite text."""

from __future__ import annotations

import re

# Em/en/thin/nbsp and other horizontal spaces LLMs insert instead of U+0020.
_UNICODE_HORIZONTAL_SPACE = re.compile(
    r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+"
)
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_MULTI_ASCII_SPACE = re.compile(r" {2,}")


def normalize_plain_spaces(text: str) -> str:
    """Replace wide/special spaces with short ASCII space; keep paragraph newlines.

    Free models often emit em-space / nbsp / narrow nbsp (e.g. ``$30 млн``),
    which render as long gaps. Editorial rule: ordinary short `` `` only.
    """
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _ZERO_WIDTH.sub("", cleaned)
    cleaned = _UNICODE_HORIZONTAL_SPACE.sub(" ", cleaned)
    lines = [_MULTI_ASCII_SPACE.sub(" ", line).strip() for line in cleaned.split("\n")]
    return "\n".join(lines)
