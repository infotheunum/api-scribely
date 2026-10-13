from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
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


# The Defiant (and the same meter) ships the lede in HTML and an empty
# ``content`` array. The article body is behind /api/content, which is 401
# without a login. A 100–400 character extract of that lede is not the story.
_WITHHELD_BODY_RE = re.compile(
    r'"contentAccess"\s*:\s*"(?:metered|pro)"'
    r'(?:(?!"content"\s*:).){0,240}'
    r'"content"\s*:\s*\[\s*\]',
    re.DOTALL,
)


@dataclass(frozen=True)
class ArticleFetch:
    """``withheld`` means the page is public but the article body is not.

    A network failure is ``text is None`` and ``withheld is False``: callers
    may keep an RSS summary. A withheld page must not be stored as that summary.
    """

    text: str | None = None
    withheld: bool = False


def article_body_withheld(html: str) -> bool:
    if _WITHHELD_BODY_RE.search(html):
        return True
    return _WITHHELD_BODY_RE.search(html.replace('\\"', '"')) is not None


def fetch_article(
    url: str, *, user_agent: str | None = None, timeout: float = 15.0
) -> ArticleFetch:
    """Downloads a page and extracts the readable article body (ТЗ §4.12)."""
    if is_video_page_url(url):
        return ArticleFetch(withheld=True)
    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("full-text fetch failed for %s", url, exc_info=True)
        return ArticleFetch()

    if article_body_withheld(response.text):
        logger.info("article body withheld for %s", url)
        return ArticleFetch(withheld=True)

    story = bloomberg_story_text(response.text)
    extracted = trafilatura.extract(response.text, url=url, favor_precision=True)
    if story and (not extracted or len(story) >= len(extracted)):
        return ArticleFetch(text=story)
    if not extracted:
        logger.warning("full-text extraction produced no content for %s", url)
        return ArticleFetch()
    return ArticleFetch(text=extracted)


def fetch_full_text(
    url: str, *, user_agent: str | None = None, timeout: float = 15.0
) -> str | None:
    """Article text, or None when the fetch failed or the body is withheld."""
    return fetch_article(url, user_agent=user_agent, timeout=timeout).text
