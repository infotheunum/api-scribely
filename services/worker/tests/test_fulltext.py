from __future__ import annotations

import json

from common.fulltext import (
    ArticleFetch,
    article_body_withheld,
    bloomberg_story_text,
    fetch_article,
    fetch_full_text,
    is_video_page_url,
)


def test_video_page_urls():
    assert is_video_page_url(
        "https://www.bloomberg.com/news/videos/2026-10-12/nobel-prize-video"
    )
    assert is_video_page_url("https://www.youtube.com/watch?v=abc")
    assert not is_video_page_url(
        "https://www.bloomberg.com/news/articles/2026-10-12/goldman-note"
    )


def test_bloomberg_story_text_keeps_paragraphs_only():
    payload = {
        "props": {
            "pageProps": {
                "story": {
                    "body": {
                        "content": [
                            {"type": "ad", "content": []},
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "value": "First sentence. "},
                                    {"type": "text", "value": "Second clause."},
                                ],
                            },
                            {
                                "type": "media",
                                "content": [{"type": "text", "value": "https://example.com/chart"}],
                            },
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "value": "Closing paragraph."}],
                            },
                        ]
                    }
                }
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    assert bloomberg_story_text(html) == "First sentence. Second clause.\n\nClosing paragraph."


def test_bloomberg_story_text_missing_on_video_shell():
    assert bloomberg_story_text("<html><title>Watch this</title></html>") is None


def test_metered_empty_content_is_withheld():
    html = (
        r'\"contentAccess\":\"metered\",\"meterPolicy\":\"pro-v2\",\"content\":[]'
    )
    assert article_body_withheld(html)
    assert not article_body_withheld('{"contentAccess":"public","content":[{"type":"p"}]}')


def test_fetch_article_withheld_does_not_return_lede(monkeypatch):
    html = '{"contentAccess":"metered","meterPolicy":"pro-v2","content":[]}'

    class _Response:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr("common.fulltext.httpx.get", lambda *a, **kw: _Response())
    monkeypatch.setattr(
        "common.fulltext.trafilatura.extract",
        lambda *a, **kw: "Ledger says the lede only.",
    )

    fetched = fetch_article("https://thedefiant.io/news/security/ledger")
    assert fetched == ArticleFetch(withheld=True)
    assert fetch_full_text("https://thedefiant.io/news/security/ledger") is None


def test_fetch_full_text_skips_video_urls(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("video pages must not be downloaded")

    monkeypatch.setattr("common.fulltext.httpx.get", _boom)
    assert fetch_full_text("https://www.bloomberg.com/news/videos/x/y-video") is None


def test_fetch_full_text_prefers_story_body_over_takeaway(monkeypatch):
    payload = {
        "props": {
            "pageProps": {
                "story": {
                    "body": {
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "value": "A" * 800}],
                            }
                        ]
                    }
                }
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    class _Response:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr("common.fulltext.httpx.get", lambda *a, **kw: _Response())
    monkeypatch.setattr("common.fulltext.trafilatura.extract", lambda *a, **kw: "short takeaway")

    text = fetch_full_text("https://www.bloomberg.com/news/articles/2026-10-12/note")
    assert text == "A" * 800
