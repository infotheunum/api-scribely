from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

import httpx
import trafilatura

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; UNUMRewriterBot/0.1; +https://theunum.io)"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_video_page_url(url: str) -> bool:
    """True for watch pages that have no article body (Bloomberg video, YouTube)."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if host in _VIDEO_HOSTS or host.endswith(".youtube.com"):
        return True
    return "/videos/" in path


def _text_values(node: object) -> list[str]:
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("value"), str):
            return [node["value"]]
        parts: list[str] = []
        for value in node.values():
            parts.extend(_text_values(value))
        return parts
    if isinstance(node, list):
        parts = []
        for item in node:
            parts.extend(_text_values(item))
        return parts
    return []


def bloomberg_story_text(html: str) -> str | None:
    """Paragraphs from Bloomberg ``__NEXT_DATA__.story.body``.

    The visible HTML often stops at the AI takeaway; the article text lives
    in this JSON. Video pages have no story body and return None.
    """
    match = _NEXT_DATA_RE.search(html)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    story = data.get("props", {}).get("pageProps", {}).get("story")
    if not isinstance(story, dict):
        return None
    content = (story.get("body") or {}).get("content")
    if not isinstance(content, list):
        return None
    paragraphs: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "paragraph":
            continue
        text = "".join(_text_values(block)).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        return None
    return "\n\n".join(paragraphs)


def fetch_full_text(
    url: str, *, user_agent: str | None = None, timeout: float = 15.0
) -> str | None:
    """Downloads a page and extracts the readable article body (ТЗ §4.12
    fallback fetch, §4.1 manual inject). Returns None on any failure —
    callers fall back to whatever summary they already have rather than
    blocking the pipeline on one flaky page (ТЗ §5)."""
    if is_video_page_url(url):
        return None
    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("full-text fetch failed for %s", url, exc_info=True)
        return None

    story = bloomberg_story_text(response.text)
    extracted = trafilatura.extract(response.text, url=url, favor_precision=True)
    if story and (not extracted or len(story) >= len(extracted)):
        return story
    if not extracted:
        logger.warning("full-text extraction produced no content for %s", url)
        return None
    return extracted
