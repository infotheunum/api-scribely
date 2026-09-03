"""Normalize rewrite body text into fixed paragraph blocks."""

from __future__ import annotations

import html
import re

from common.text_spaces import normalize_plain_spaces

EXPECTED_PARAGRAPH_COUNT = 3

_PARA_BREAK = re.compile(r"\n\s*\n+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def split_paragraphs(text: str) -> list[str]:
    """Return non-empty paragraph chunks from plain text."""
    normalized = normalize_plain_spaces(text or "").strip()
    if not normalized:
        return []
    if _PARA_BREAK.search(normalized):
        return [part.strip() for part in _PARA_BREAK.split(normalized) if part.strip()]
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if len(lines) >= 2:
        return lines
    sentences = [part.strip() for part in _SENTENCE_END.split(normalized) if part.strip()]
    if len(sentences) >= 2:
        return sentences
    return [normalized]


def _group_into_n(parts: list[str], count: int) -> list[str]:
    if count <= 0 or not parts:
        return parts
    if len(parts) <= count:
        return parts
    groups: list[list[str]] = [[] for _ in range(count)]
    group_lens = [0] * count
    for part in parts:
        idx = group_lens.index(min(group_lens))
        groups[idx].append(part)
        group_lens[idx] += len(part) + 1
    return [" ".join(group).strip() for group in groups if group]


def _split_by_char_chunks(text: str, count: int) -> list[str]:
    chunk = text.strip()
    if not chunk or count <= 1:
        return [chunk] if chunk else []
    size = max(1, len(chunk) // count)
    parts: list[str] = []
    start = 0
    for index in range(count):
        if index == count - 1:
            parts.append(chunk[start:])
            break
        end = min(len(chunk), start + size)
        scan = end
        while scan > start and chunk[scan - 1] not in " \t":
            scan -= 1
        if scan > start:
            end = scan
        parts.append(chunk[start:end])
        start = end
    return [part for part in parts if part]


def _split_longest_paragraph(paragraphs: list[str]) -> list[str]:
    if not paragraphs:
        return paragraphs
    idx = max(range(len(paragraphs)), key=lambda i: len(paragraphs[i]))
    chunk = paragraphs[idx]
    sentences = [part.strip() for part in _SENTENCE_END.split(chunk) if part.strip()]
    if len(sentences) >= 2:
        split = _group_into_n(sentences, 2)
    else:
        words = chunk.split()
        split = _group_into_n(words, 2) if len(words) >= 2 else _split_by_char_chunks(chunk, 2)
    if len(split) < 2:
        return paragraphs
    return paragraphs[:idx] + split + paragraphs[idx + 1 :]


def _coalesce_to_count(paragraphs: list[str], count: int) -> list[str]:
    paras = [part.strip() for part in paragraphs if part.strip()]
    while len(paras) > count:
        best_i = 0
        best_len = len(paras[0]) + len(paras[1])
        for i in range(len(paras) - 1):
            combined = len(paras[i]) + len(paras[i + 1])
            if combined < best_len:
                best_len = combined
                best_i = i
        merged = f"{paras[best_i]} {paras[best_i + 1]}".strip()
        paras = paras[:best_i] + [merged] + paras[best_i + 2 :]
    while len(paras) < count:
        paras = _split_longest_paragraph(paras)
        if len(paras) < count and len(paras) == 1:
            paras = _split_by_char_chunks(paras[0], count)
            break
    return paras[:count]


def normalize_body_paragraphs(text: str, *, expected: int = EXPECTED_PARAGRAPH_COUNT) -> str:
    """Ensure body uses blank-line paragraph breaks (\\n\\n)."""
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return ""
    if len(paragraphs) != expected:
        parts = paragraphs
        if len(parts) == 1:
            sentences = [part.strip() for part in _SENTENCE_END.split(parts[0]) if part.strip()]
            if len(sentences) >= expected:
                parts = sentences
            elif len(parts[0].split()) >= expected:
                parts = _group_into_n(parts[0].split(), expected)
            else:
                parts = _split_by_char_chunks(parts[0], expected)
        paragraphs = _coalesce_to_count(parts, expected)
    return "\n\n".join(paragraphs[:expected])


def body_to_html(text: str) -> str:
    """Render normalized paragraphs as simple HTML for CMS import."""
    paragraphs = split_paragraphs(normalize_body_paragraphs(text))
    return "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)


def paragraph_count(text: str) -> int:
    return len(split_paragraphs(normalize_body_paragraphs(text)))
