from __future__ import annotations

import calendar
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx
from common.fulltext import DEFAULT_USER_AGENT

# Below this length a feed entry is treated as "summary-only" and, for
# Tier 1 sources, triggers the fallback full-text fetch (ТЗ §4.1, §4.12).
# WordPress/Arc-style excerpts are typically well under this; genuine
# full-content feeds (content:encoded) usually clear it easily.
SUMMARY_ONLY_THRESHOLD_CHARS = 600


class FeedFetchError(Exception):
    """Raised when the feed itself can't be retrieved/parsed — distinct
    from per-entry issues, which are just skipped."""


@dataclass
class ParsedEntry:
    external_id: str
    url: str
    title: str
    summary: str | None
    published_at: datetime | None

    @property
    def looks_summary_only(self) -> bool:
        return not self.summary or len(self.summary) < SUMMARY_ONLY_THRESHOLD_CHARS


def _to_datetime(struct: time.struct_time | None) -> datetime | None:
    if struct is None:
        return None
    # feedparser normalizes *_parsed fields to UTC struct_time already —
    # timegm (not mktime, which assumes local time) is the correct inverse.
    return datetime.fromtimestamp(calendar.timegm(struct), tz=UTC)


def _entry_external_id(entry: dict) -> str | None:
    return entry.get("id") or entry.get("guid") or entry.get("link")


def _entry_text(entry: dict) -> str | None:
    # Prefer <content:encoded> (often the full article) over <description>.
    content_list = entry.get("content")
    if content_list:
        value = content_list[0].get("value")
        if value:
            return value
    return entry.get("summary")


def fetch_feed_entries(
    feed_url: str, *, user_agent: str | None = None, timeout: float = 15.0
) -> list[ParsedEntry]:
    """Fetches and parses an RSS/Atom feed. Raises FeedFetchError on
    transport-level failure (feeds the circuit breaker); malformed
    individual entries are skipped rather than failing the whole feed."""
    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    try:
        response = httpx.get(feed_url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FeedFetchError(f"could not fetch {feed_url}: {exc}") from exc

    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        # A real feed practically never has zero items — this usually
        # means the response wasn't actually a feed (e.g. an HTML
        # challenge/error page returned with a 200 status, so
        # raise_for_status() above didn't catch it). feedparser is lenient
        # enough that this often parses "successfully" with bozo=False,
        # so entry count — not the bozo flag — is the real signal here.
        # Worth counting as a failure against the circuit breaker rather
        # than silently treating it as "nothing new this cycle".
        raise FeedFetchError(f"feed at {feed_url} produced zero entries")

    entries: list[ParsedEntry] = []
    for raw_entry in parsed.entries:
        external_id = _entry_external_id(raw_entry)
        url = raw_entry.get("link")
        if not external_id or not url:
            continue
        entries.append(
            ParsedEntry(
                external_id=external_id,
                url=url,
                title=raw_entry.get("title", "").strip(),
                summary=_entry_text(raw_entry),
                published_at=_to_datetime(raw_entry.get("published_parsed")),
            )
        )
    return entries
