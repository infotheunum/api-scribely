from __future__ import annotations

import httpx
import pytest
from worker_app.ingestion.rss_connector import FeedFetchError, fetch_feed_entries

FULL_CONTENT_BODY = "This is the full article body. " * 30  # comfortably > 600 chars

SAMPLE_FEED = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Sample Feed</title>
  <item>
    <title>Full content article</title>
    <link>https://example.com/full</link>
    <guid>https://example.com/full</guid>
    <description>Short teaser.</description>
    <content:encoded><![CDATA[{FULL_CONTENT_BODY}]]></content:encoded>
    <pubDate>Mon, 03 Aug 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Summary only article</title>
    <link>https://example.com/summary</link>
    <guid>https://example.com/summary</guid>
    <description>Just a short teaser, nothing more.</description>
    <pubDate>Mon, 03 Aug 2026 13:00:00 GMT</pubDate>
  </item>
</channel>
</rss>
""".encode()


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def test_fetch_feed_entries_parses_and_normalizes(monkeypatch):
    monkeypatch.setattr(
        "worker_app.ingestion.rss_connector.httpx.get",
        lambda *a, **kw: _FakeResponse(SAMPLE_FEED),
    )

    entries = fetch_feed_entries("https://example.com/feed")

    assert len(entries) == 2
    full, summary_only = entries

    assert full.external_id == "https://example.com/full"
    assert full.url == "https://example.com/full"
    assert len(full.summary) > 600
    assert not full.looks_summary_only

    assert summary_only.title == "Summary only article"
    assert summary_only.looks_summary_only
    assert summary_only.published_at is not None


def test_fetch_feed_entries_raises_on_transport_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("worker_app.ingestion.rss_connector.httpx.get", _raise)

    with pytest.raises(FeedFetchError):
        fetch_feed_entries("https://example.com/feed")


def test_fetch_feed_entries_raises_on_unparseable_content(monkeypatch):
    monkeypatch.setattr(
        "worker_app.ingestion.rss_connector.httpx.get",
        lambda *a, **kw: _FakeResponse(b"<html><body>Just a moment...</body></html>"),
    )

    with pytest.raises(FeedFetchError):
        fetch_feed_entries("https://example.com/feed")
