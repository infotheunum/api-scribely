from __future__ import annotations

import logging

import httpx
import trafilatura

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; UNUMRewriterBot/0.1; +https://theunum.io)"


def fetch_full_text(
    url: str, *, user_agent: str | None = None, timeout: float = 15.0
) -> str | None:
    """Downloads a page and extracts the readable article body (ТЗ §4.12
    fallback fetch, §4.1 manual inject). Returns None on any failure —
    callers fall back to whatever summary they already have rather than
    blocking the pipeline on one flaky page (ТЗ §5)."""
    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("full-text fetch failed for %s", url, exc_info=True)
        return None

    text = trafilatura.extract(response.text, url=url, favor_precision=True)
    if not text:
        logger.warning("full-text extraction produced no content for %s", url)
        return None
    return text
