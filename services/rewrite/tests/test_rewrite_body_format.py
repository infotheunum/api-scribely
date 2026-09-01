from __future__ import annotations

from common.rewrite_body_format import (
    EXPECTED_PARAGRAPH_COUNT,
    body_to_html,
    normalize_body_paragraphs,
    paragraph_count,
    split_paragraphs,
)


def test_split_paragraphs_on_blank_line():
    text = "Lead paragraph.\n\nMiddle paragraph.\n\nClosing paragraph."
    assert split_paragraphs(text) == [
        "Lead paragraph.",
        "Middle paragraph.",
        "Closing paragraph.",
    ]


def test_split_paragraphs_on_single_newlines():
    text = "One.\nTwo.\nThree."
    assert split_paragraphs(text) == ["One.", "Two.", "Three."]


def test_normalize_splits_long_unbroken_text():
    text = "x" * 1800
    normalized = normalize_body_paragraphs(text)
    assert paragraph_count(normalized) == EXPECTED_PARAGRAPH_COUNT
    assert len(normalized) == 1800 + 2 * (EXPECTED_PARAGRAPH_COUNT - 1)


    text = (
        "First sentence starts the story. Second sentence adds detail. "
        "Third sentence continues. Fourth sentence expands context. "
        "Fifth sentence introduces numbers. Sixth sentence wraps up."
    )
    normalized = normalize_body_paragraphs(text)
    assert paragraph_count(normalized) == EXPECTED_PARAGRAPH_COUNT
    assert normalized.count("\n\n") == 2


def test_normalize_merges_extra_paragraphs():
    text = "One.\n\nTwo.\n\nThree.\n\nFour.\n\nFive."
    normalized = normalize_body_paragraphs(text)
    assert paragraph_count(normalized) == EXPECTED_PARAGRAPH_COUNT


def test_body_to_html_escapes_and_wraps_paragraphs():
    text = 'Lead with <tag> & "quote".\n\nSecond paragraph.\n\nThird paragraph.'
    html = body_to_html(text)
    assert html == (
        "<p>Lead with &lt;tag&gt; &amp; &quot;quote&quot;.</p>"
        "<p>Second paragraph.</p>"
        "<p>Third paragraph.</p>"
    )
