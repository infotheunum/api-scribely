from __future__ import annotations

from db.models import AuditLog
from sqlalchemy import select


def _auth_headers(client, user):
    resp = client.post(
        "/auth/login", data={"username": user.username, "password": "correct-horse-battery-staple"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_endpoints_require_admin_role(client, test_user, clean_db):
    resp = client.get("/admin/sources", headers=_auth_headers(client, test_user))
    assert resp.status_code == 403


def test_admin_endpoints_require_auth(client, clean_db):
    resp = client.get("/admin/sources")
    assert resp.status_code == 401


def test_create_and_list_source(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    resp = client.post(
        "/admin/sources",
        json={"name": "New Wire", "url": "https://example.com/feed", "tier": 1, "language": "en"},
        headers=headers,
    )
    assert resp.status_code == 201
    source_id = resp.json()["id"]

    listed = client.get("/admin/sources", headers=headers).json()
    assert any(s["id"] == source_id and s["name"] == "New Wire" for s in listed)

    audit = clean_db.scalars(
        select(AuditLog).where(AuditLog.entity_type == "Source", AuditLog.entity_id == source_id)
    ).first()
    assert audit is not None
    assert audit.action == "admin_create"


def test_patch_source_disables_it(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    created = client.post(
        "/admin/sources",
        json={"name": "Toggle Me", "url": "https://example.com/f2", "tier": 1},
        headers=headers,
    ).json()

    resp = client.patch(
        f"/admin/sources/{created['id']}", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_create_topic_rejects_duplicate_name(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    body = {"name": "Test Topic", "keywords": ["foo", "bar"]}
    first = client.post("/admin/topics", json=body, headers=headers)
    assert first.status_code == 201

    second = client.post("/admin/topics", json=body, headers=headers)
    assert second.status_code == 409


def test_topic_can_be_deactivated_via_patch(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    created = client.post(
        "/admin/topics", json={"name": "Deactivate Me", "keywords": ["x"]}, headers=headers
    ).json()

    resp = client.patch(
        f"/admin/topics/{created['id']}", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_llm_model_rejects_fourth_active(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    for i in range(3):
        resp = client.post(
            "/admin/llm-models",
            json={"model_id": f"vendor/model-{i}:free", "position": i, "is_active": True},
            headers=headers,
        )
        assert resp.status_code == 201

    fourth = client.post(
        "/admin/llm-models",
        json={"model_id": "vendor/model-4:free", "position": 4, "is_active": True},
        headers=headers,
    )
    assert fourth.status_code == 409

    # inactive is still fine even with 3 already active
    inactive_ok = client.post(
        "/admin/llm-models",
        json={"model_id": "vendor/model-5:free", "position": 5, "is_active": False},
        headers=headers,
    )
    assert inactive_ok.status_code == 201


def test_llm_model_patch_rejects_activating_a_fourth(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    for i in range(3):
        client.post(
            "/admin/llm-models",
            json={"model_id": f"vendor/active-{i}:free", "position": i, "is_active": True},
            headers=headers,
        )
    spare = client.post(
        "/admin/llm-models",
        json={"model_id": "vendor/spare:free", "position": 9, "is_active": False},
        headers=headers,
    ).json()

    resp = client.patch(
        f"/admin/llm-models/{spare['id']}", json={"is_active": True}, headers=headers
    )
    assert resp.status_code == 409


def test_upsert_setting_creates_then_updates(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    first = client.put(
        "/admin/settings/dispatch.batch_size",
        json={"value": 2, "description": "test knob"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["value"] == 2

    second = client.put("/admin/settings/dispatch.batch_size", json={"value": 5}, headers=headers)
    assert second.status_code == 200
    assert second.json()["value"] == 5

    listed = client.get("/admin/settings", headers=headers).json()
    assert any(s["key"] == "dispatch.batch_size" and s["value"] == 5 for s in listed)


def test_prompt_version_create_and_activate(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    v1 = client.post(
        "/admin/prompt-versions",
        json={"template": "v1 template", "notes": "first"},
        headers=headers,
    ).json()
    assert v1["status"] == "draft"

    activated = client.post(f"/admin/prompt-versions/{v1['id']}/activate", headers=headers)
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    v2 = client.post(
        "/admin/prompt-versions", json={"template": "v2 template"}, headers=headers
    ).json()
    client.post(f"/admin/prompt-versions/{v2['id']}/activate", headers=headers)

    listed = {
        v["id"]: v["status"] for v in client.get("/admin/prompt-versions", headers=headers).json()
    }
    assert listed[v1["id"]] == "retired"
    assert listed[v2["id"]] == "active"
