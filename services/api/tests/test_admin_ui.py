from __future__ import annotations


def _auth_headers(client, user):
    resp = client.post(
        "/auth/login", data={"username": user.username, "password": "correct-horse-battery-staple"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_ui_redirects_anonymous_to_login(client, clean_db):
    resp = client.get("/ui/admin/sources", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"


def test_admin_ui_hidden_from_rewriter_role(client, test_user, clean_db):
    resp = client.get(
        "/ui/admin/sources", headers=_auth_headers(client, test_user), follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/drafts"


def test_admin_ui_sources_create_and_toggle(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    resp = client.post(
        "/ui/admin/sources",
        data={
            "name": "New Wire",
            "url": "https://example.com/feed",
            "tier": "1",
            "language": "en",
            "poll_interval_seconds": "900",
        },
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listed = client.get("/ui/admin/sources", headers=headers)
    assert listed.status_code == 200
    assert "New Wire" in listed.text

    from db.models import Source

    source = clean_db.query(Source).filter_by(name="New Wire").one()
    assert source.is_active is True

    client.post(
        f"/ui/admin/sources/{source.id}/toggle",
        data={"is_active": "false"},
        headers=headers,
        follow_redirects=False,
    )
    clean_db.refresh(source)
    assert source.is_active is False


def test_admin_ui_topics_create_and_edit_keywords(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/topics",
        data={"name": "Bitcoin", "keywords": "btc, halving"},
        headers=headers,
        follow_redirects=False,
    )

    from db.models import Topic

    topic = clean_db.query(Topic).filter_by(name="Bitcoin").one()
    assert topic.keywords == ["btc", "halving"]

    client.post(
        f"/ui/admin/topics/{topic.id}/keywords",
        data={"keywords": "btc, etf, halving"},
        headers=headers,
        follow_redirects=False,
    )
    clean_db.refresh(topic)
    assert topic.keywords == ["btc", "etf", "halving"]


def test_admin_ui_llm_models_enforces_max_active(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    for i in range(3):
        resp = client.post(
            "/ui/admin/llm-models",
            data={"model_id": f"model-{i}:free", "position": str(i), "is_active": "true"},
            headers=headers,
            follow_redirects=False,
        )
        assert resp.status_code == 303

    resp = client.post(
        "/ui/admin/llm-models",
        data={"model_id": "model-3:free", "position": "3", "is_active": "true"},
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]

    from db.models import LlmRotationModel

    assert clean_db.query(LlmRotationModel).filter_by(model_id="model-3:free").count() == 0


def test_admin_ui_settings_upsert_parses_json_value(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/settings",
        data={"key": "queue.ttl_archive_hours", "value": "48", "description": "ttl"},
        headers=headers,
        follow_redirects=False,
    )

    from db.models import AppSetting

    setting = clean_db.get(AppSetting, "queue.ttl_archive_hours")
    assert setting.value == 48


def test_admin_ui_prompt_versions_create_and_activate(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    resp = client.post(
        "/ui/admin/prompt-versions",
        data={"template": "rewrite this: {{body}}", "notes": "v2"},
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    from db.models import PromptVersion

    version = clean_db.query(PromptVersion).filter_by(notes="v2").one()
    assert version.status == "draft"

    client.post(
        f"/ui/admin/prompt-versions/{version.id}/activate", headers=headers, follow_redirects=False
    )
    clean_db.refresh(version)
    assert version.status == "active"

    page = client.get("/ui/admin/prompt-versions", headers=headers)
    assert page.status_code == 200
    assert "rewrite this" in page.text
