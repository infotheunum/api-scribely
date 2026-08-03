from __future__ import annotations

import uuid

import pytest
from api_app.db import _session_factory
from db.enums import SourceTier, SourceType
from db.models import RawItem, Source
from sqlalchemy import select


@pytest.fixture
def manual_source():
    session = _session_factory()()
    source = session.scalar(select(Source).where(Source.type == SourceType.MANUAL))
    created = source is None
    if created:
        source = Source(
            name="Manual Inject",
            url="manual://inject",
            type=SourceType.MANUAL,
            tier=SourceTier.TIER_1,
            language="en",
        )
        session.add(source)
        session.commit()
        session.refresh(source)
    try:
        yield source
    finally:
        if created:
            session.execute(RawItem.__table__.delete().where(RawItem.source_id == source.id))
            session.delete(source)
            session.commit()
        session.close()


def _auth_headers(client, test_user):
    resp = client.post(
        "/auth/login",
        data={"username": test_user.username, "password": "correct-horse-battery-staple"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_inject_requires_auth(client, manual_source):
    resp = client.post("/ingestion/inject", json={"url": "https://example.com/article"})
    assert resp.status_code == 401


def test_inject_creates_raw_item(client, test_user, manual_source, monkeypatch):
    monkeypatch.setattr(
        "api_app.routers.ingestion.fetch_full_text", lambda *a, **kw: "the fetched article body"
    )
    url = f"https://example.com/article-{uuid.uuid4().hex}"

    resp = client.post(
        "/ingestion/inject", json={"url": url}, headers=_auth_headers(client, test_user)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] is True

    session = _session_factory()()
    raw_item = session.get(RawItem, uuid.UUID(body["raw_item_id"]))
    assert raw_item is not None
    assert raw_item.url == url
    assert raw_item.body == "the fetched article body"
    assert raw_item.is_manual_inject is True
    session.close()


def test_inject_same_url_twice_is_idempotent(client, test_user, manual_source, monkeypatch):
    monkeypatch.setattr("api_app.routers.ingestion.fetch_full_text", lambda *a, **kw: "body")
    url = f"https://example.com/dup-{uuid.uuid4().hex}"
    headers = _auth_headers(client, test_user)

    first = client.post("/ingestion/inject", json={"url": url}, headers=headers)
    second = client.post("/ingestion/inject", json={"url": url}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["raw_item_id"] == second.json()["raw_item_id"]
