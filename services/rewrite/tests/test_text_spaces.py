from __future__ import annotations

from common.text_spaces import normalize_plain_spaces


def test_normalize_plain_spaces_replaces_unicode_and_collapses():
    raw = "BitMine\u2003Adds\u00a053\u202f501 ETH  today"
    assert normalize_plain_spaces(raw) == "BitMine Adds 53 501 ETH today"


def test_normalize_plain_spaces_keeps_paragraph_breaks():
    raw = "One.\n\nTwo\u00a0words.\n\nThree."
    assert normalize_plain_spaces(raw) == "One.\n\nTwo words.\n\nThree."
