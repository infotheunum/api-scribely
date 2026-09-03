from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from db.app_settings import set_setting
from db.enums import DraftStatus, SourceTier, SourceType
from db.models import Draft, DraftExportLog, NewsCluster, RawItem, Source
from sqlalchemy import func, select

INTEGRATION_TOKEN = "test-theunum-integration-token"
AUTH_HEADERS = {"Authorization": f"Bearer {INTEGRATION_TOKEN}"}


@pytest.fixture(autouse=True)
def integration_token(monkeypatch):
    monkeypatch.setenv("THEUNUM_INTEGRATION_TOKEN", INTEGRATION_TOKEN)


@pytest.fixture(autouse=True)
def mock_rewrite_reachable(monkeypatch):
    """Integration meta/status tests don't run a real rewrite gRPC server."""
    monkeypatch.setattr(
        "api_app.integrations.pipeline_status.check_rewrite_health",
        lambda _channel: True,
    )


def _source(db) -> Source:
    source = Source(
        name="Export Wire",
        url="https://example.com/export-feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _cluster(db, source) -> NewsCluster:
    cluster = NewsCluster(trace_id="export-t", topic="Криптовалюты")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id=f"export-{cluster.id}",
            url=f"https://example.com/export/{cluster.id}",
            title="Source headline",
            body="Source body",
            language="en",
            trace_id="export-t",
            cluster_id=cluster.id,
        )
    )
    db.commit()
    db.refresh(cluster)
    return cluster


def _draft(db, cluster, **overrides) -> Draft:
    defaults = dict(
        cluster_id=cluster.id,
        title_en="Bitcoin ETF inflows hit record",
        body_en="English body " * 20,
        title_ru="Приток в Bitcoin ETF",
        body_ru="Русский текст " * 20,
        attribution_urls=["https://example.com/a"],
        trace_id="export-t",
        status=DraftStatus.READY_FOR_REVIEW,
    )
    defaults.update(overrides)
    draft = Draft(**defaults)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_integration_requires_token(client, clean_db):
    resp = client.get("/integrations/theunum/v1/drafts")
    assert resp.status_code == 401


def test_integration_accepts_x_theunum_service_token_header(client, clean_db):
    resp = client.get(
        "/integrations/theunum/v1/drafts",
        headers={"X-Theunum-Service-Token": INTEGRATION_TOKEN},
    )
    assert resp.status_code == 200


def test_integration_not_configured_returns_503(client, clean_db, monkeypatch):
    from api_app.auth import integration as integration_auth

    class _UnsetToken:
        theunum_integration_token = ""

    monkeypatch.setattr(integration_auth, "ApiSettings", lambda: _UnsetToken())
    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert resp.status_code == 503


def test_list_pagination_cursor(client, clean_db):
    source = _source(clean_db)
    cluster1 = _cluster(clean_db, source)
    cluster2 = _cluster(clean_db, source)
    older = _draft(clean_db, cluster1, title_en="Older draft title here xx")
    newer = _draft(clean_db, cluster2, title_en="Newer draft title here xx")
    older.content_generated_at = datetime.now(UTC) - timedelta(hours=1)
    newer.content_generated_at = datetime.now(UTC)
    clean_db.commit()

    first_page = client.get(
        "/integrations/theunum/v1/drafts?limit=1",
        headers=AUTH_HEADERS,
    )
    assert first_page.status_code == 200
    body = first_page.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(newer.id)
    assert body["has_more"] is True
    assert body["next_cursor"] is not None

    second_page = client.get(
        f"/integrations/theunum/v1/drafts?limit=1&cursor={body['next_cursor']}",
        headers=AUTH_HEADERS,
    )
    assert second_page.status_code == 200
    page2 = second_page.json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] == str(older.id)


def test_list_empty_queue_meta(client, clean_db):
    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["has_more"] is False
    assert body["meta"]["reason_code"] == "queue_empty"


def test_list_returns_bilingual_draft(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(
        clean_db,
        cluster,
        body_en="Lead paragraph one.\n\nMiddle paragraph two.\n\nClosing paragraph three.",
        body_ru="Лид абзац.\n\nСередина абзац.\n\nФинал абзац.",
    )

    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(draft.id)
    assert items[0]["title_en"]
    assert items[0]["title_ru"]
    assert "\n\n" in items[0]["body_en"]
    assert items[0]["body_en_html"].startswith("<p>")
    assert items[0]["body_en_html"].count("<p>") == 3
    assert items[0]["body_ru_html"].count("<p>") == 3
    assert items[0]["consumed_at"] is None


def test_list_orders_newest_content_generated_first(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    older = _draft(clean_db, cluster, title_en="Older generated draft title xx")
    newer = _draft(clean_db, cluster, title_en="Newer generated draft title xx")
    older.content_generated_at = datetime.now(UTC) - timedelta(hours=2)
    newer.content_generated_at = datetime.now(UTC)
    clean_db.commit()

    resp = client.get("/integrations/theunum/v1/drafts?limit=10", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids.index(str(newer.id)) < ids.index(str(older.id))


def test_list_filters_by_generated_since(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    fresh = _draft(clean_db, cluster, title_en="Fresh draft title here today")
    stale = _draft(clean_db, cluster, title_en="Stale draft title here today")
    stale.content_generated_at = datetime.now(UTC) - timedelta(days=30)
    clean_db.commit()

    since = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    resp = client.get(
        f"/integrations/theunum/v1/drafts?generated_since={since}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(fresh.id) in ids
    assert str(stale.id) not in ids


def test_list_includes_content_generated_at(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)
    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    item = resp.json()["items"][0]
    assert item["content_generated_at"]
    assert item["updated_at"]
    assert item["created_at"]
    assert item["id"] == str(draft.id)


def test_list_freshness_today_excludes_yesterday(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    fresh = _draft(clean_db, cluster, title_en="Today draft title here now")
    stale = _draft(clean_db, cluster, title_en="Yesterday draft title here now")
    stale.content_generated_at = datetime.now(UTC) - timedelta(days=1)
    clean_db.commit()

    resp = client.get(
        "/integrations/theunum/v1/drafts?freshness=today",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(fresh.id) in ids
    assert str(stale.id) not in ids
    assert body["meta"]["freshness"] == "today"
    assert body["meta"]["content_generated_since"]


def test_drafts_today_endpoint(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster, title_en="Today shortcut draft title")
    resp = client.get("/integrations/theunum/v1/drafts/today", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["id"] == str(draft.id)


def test_list_freshness_48h(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    fresh = _draft(clean_db, cluster, title_en="Recent draft title here now")
    stale = _draft(clean_db, cluster, title_en="Old draft title here now")
    stale.created_at = datetime.now(UTC) - timedelta(hours=72)
    stale.content_generated_at = datetime.now(UTC)
    clean_db.commit()

    resp = client.get(
        "/integrations/theunum/v1/drafts?freshness=48h",
        headers=AUTH_HEADERS,
    )
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(fresh.id) in ids
    assert str(stale.id) not in ids
    assert body["meta"]["freshness"] == "48h"
    assert body["meta"]["created_since"]


def test_list_uses_admin_default_freshness(client, clean_db):
    from common.integration_export_settings import DEFAULT_FRESHNESS_KEY
    from db.app_settings import set_setting

    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    fresh = _draft(clean_db, cluster, title_en="Today draft from admin default")
    stale = _draft(clean_db, cluster, title_en="Yesterday draft excluded by admin")
    stale.content_generated_at = datetime.now(UTC) - timedelta(days=1)
    set_setting(clean_db, DEFAULT_FRESHNESS_KEY, "today")
    clean_db.commit()

    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(fresh.id) in ids
    assert str(stale.id) not in ids
    assert body["meta"]["freshness_source"] == "admin_default"
    assert body["meta"]["freshness"] == "today"


def test_export_schema_endpoint(client, clean_db):
    resp = client.get("/integrations/theunum/v1/export-schema", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["defaults"]["default_freshness"] == ""
    assert len(body["filters"]) >= 7
    assert len(body["unsupported"]) >= 10
    assert body["endpoints"]["list"].endswith("/drafts")


def test_list_uses_admin_default_limit(client, clean_db):
    from common.integration_export_settings import DEFAULT_LIMIT_KEY

    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    for i in range(3):
        _draft(clean_db, cluster, title_en=f"Draft number {i} for limit test")
    set_setting(clean_db, DEFAULT_LIMIT_KEY, 2)
    clean_db.commit()

    resp = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["meta"]["limit"] == 2
    assert body["meta"]["limit_source"] == "admin_default"
    assert body["has_more"] is True


def test_mark_consumed_excludes_from_list(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    mark = client.post(
        f"/integrations/theunum/v1/drafts/{draft.id}/mark-consumed",
        headers=AUTH_HEADERS,
        json={"theunum_reference_id": "theunum-42"},
    )
    assert mark.status_code == 200
    assert mark.json()["marked"] == 1

    unconsumed = client.get(
        "/integrations/theunum/v1/drafts?consumed=false",
        headers=AUTH_HEADERS,
    )
    assert unconsumed.json()["items"] == []

    # Omit consumed → still returns marked drafts (debug / ignore consume flag).
    all_today = client.get("/integrations/theunum/v1/drafts", headers=AUTH_HEADERS)
    assert len(all_today.json()["items"]) == 1
    assert all_today.json()["items"][0]["id"] == str(draft.id)
    assert all_today.json()["items"][0]["consumed_at"] is not None

    export_log = clean_db.get(DraftExportLog, draft.id)
    assert export_log is not None
    assert export_log.theunum_reference_id == "theunum-42"


def test_mark_consumed_batch_idempotent(client, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    payload = {"items": [{"draft_id": str(draft.id), "theunum_reference_id": "x"}]}
    first = client.post(
        "/integrations/theunum/v1/drafts/mark-consumed",
        headers=AUTH_HEADERS,
        json=payload,
    )
    second = client.post(
        "/integrations/theunum/v1/drafts/mark-consumed",
        headers=AUTH_HEADERS,
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert clean_db.scalar(select(func.count()).select_from(DraftExportLog)) == 1


def test_status_reports_degraded_openrouter(client, clean_db):
    set_setting(
        clean_db,
        "pipeline.last_error_code",
        "openrouter_payment_required",
        description="test",
    )
    set_setting(
        clean_db,
        "pipeline.last_error_message",
        "OpenRouter error: insufficient credits",
        description="test",
    )
    set_setting(clean_db, "pipeline.last_dispatch_failed", 2, description="test")
    clean_db.commit()

    resp = client.get("/integrations/theunum/v1/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["openrouter"]["last_error_code"] == "openrouter_payment_required"


def test_empty_batch_mark_consumed(client, clean_db):
    resp = client.post(
        "/integrations/theunum/v1/drafts/mark-consumed",
        headers=AUTH_HEADERS,
        json={"items": []},
    )
    assert resp.status_code == 200
    assert resp.json()["marked"] == 0
