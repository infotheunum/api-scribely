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


def test_admin_ui_sources_delete(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/sources",
        data={
            "name": "Remove Me",
            "url": "https://example.com/remove",
            "tier": "2",
            "language": "en",
            "poll_interval_seconds": "900",
        },
        headers=headers,
        follow_redirects=False,
    )

    from db.models import Source

    source = clean_db.query(Source).filter_by(name="Remove Me").one()
    resp = client.post(
        f"/ui/admin/sources/{source.id}/delete",
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listed = client.get("/ui/admin/sources", headers=headers)
    assert "Remove Me" not in listed.text
    clean_db.refresh(source)
    assert source.deleted_at is not None
    assert source.is_active is False


def test_admin_ui_sources_pagination(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    for i in range(1, 8):
        resp = client.post(
            "/ui/admin/sources",
            data={
                "name": f"Page Source {i:02d}",
                "url": f"https://example.com/page-{i}",
                "tier": "1",
                "language": "en",
                "poll_interval_seconds": "900",
            },
            headers=headers,
            follow_redirects=False,
        )
        assert resp.status_code == 303

    page1 = client.get("/ui/admin/sources?per_page=5", headers=headers)
    assert page1.status_code == 200
    assert "Page Source 01" in page1.text
    assert "Page Source 05" in page1.text
    assert "Page Source 06" not in page1.text
    assert "1–5 из 7" in page1.text
    assert "стр. 1 / 2" in page1.text
    assert 'href="/ui/admin/sources?page=2&amp;per_page=5"' in page1.text

    page2 = client.get("/ui/admin/sources?page=2&per_page=5", headers=headers)
    assert page2.status_code == 200
    assert "Page Source 06" in page2.text
    assert "Page Source 07" in page2.text
    assert "Page Source 01" not in page2.text
    assert "6–7 из 7" in page2.text
    assert "стр. 2 / 2" in page2.text

    from db.models import Source

    last = clean_db.query(Source).filter_by(name="Page Source 07").one()
    toggle = client.post(
        f"/ui/admin/sources/{last.id}/toggle",
        data={"is_active": "false", "page": "2"},
        headers=headers,
        follow_redirects=False,
    )
    assert toggle.status_code == 303
    assert toggle.headers["location"] == "/ui/admin/sources?page=2"


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


def test_admin_ui_export_freshness_defaults(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/settings/export-freshness",
        data={"default_freshness": "48h", "default_max_age_hours": "24", "default_limit": "100"},
        headers=headers,
        follow_redirects=False,
    )

    from db.models import AppSetting

    assert clean_db.get(AppSetting, "integration.export.default_freshness").value == "48h"
    assert clean_db.get(AppSetting, "integration.export.default_max_age_hours").value == 24
    assert clean_db.get(AppSetting, "integration.export.default_limit").value == 100

    page = client.get("/ui/admin/settings", headers=headers)
    assert page.status_code == 200
    assert "Export API" in page.text


def test_admin_ui_generation_hours(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/settings/generation-hours",
        data={
            "enabled": "1",
            "timezone_name": "Europe/Minsk",
            "weekend_daily_limit": "50",
            "day_0_enabled": "1",
            "day_0_start": "6",
            "day_0_end": "18",
            "day_1_enabled": "1",
            "day_1_start": "6",
            "day_1_end": "18",
            "day_2_enabled": "1",
            "day_2_start": "6",
            "day_2_end": "18",
            "day_3_enabled": "1",
            "day_3_start": "6",
            "day_3_end": "18",
            "day_4_enabled": "1",
            "day_4_start": "6",
            "day_4_end": "18",
            "day_5_enabled": "1",
            "day_5_start": "9",
            "day_5_end": "12",
            "day_6_start": "9",
            "day_6_end": "12",
            # Sunday unchecked → disabled
        },
        headers=headers,
        follow_redirects=False,
    )

    from db.models import AppSetting

    assert clean_db.get(AppSetting, "pipeline.generation_hours_enabled").value is True
    schedule = clean_db.get(AppSetting, "pipeline.generation_schedule").value
    assert schedule["0"]["start"] == 6
    assert schedule["5"]["enabled"] is True
    assert schedule["5"]["start"] == 9
    assert schedule["5"]["end"] == 12
    assert schedule["6"]["enabled"] is False
    assert clean_db.get(AppSetting, "queue.weekend_daily_limit").value == 50

    page = client.get("/ui/admin/settings", headers=headers)
    assert page.status_code == 200
    assert "Окно генерации" in page.text
    assert "Пн" in page.text
    assert "Лимит черновиков в выходные" in page.text


def test_admin_ui_output_locales(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    client.post(
        "/ui/admin/settings/output-locales",
        data={"locale_ru": "1", "locale_en": "1"},
        headers=headers,
        follow_redirects=False,
    )
    from db.models import AppSetting

    assert clean_db.get(AppSetting, "rewrite.output_locales").value == ["ru", "en"]

    client.post(
        "/ui/admin/settings/output-locales",
        data={"locale_ru": "1"},
        headers=headers,
        follow_redirects=False,
    )
    assert clean_db.get(AppSetting, "rewrite.output_locales").value == ["ru"]

    page = client.get("/ui/admin/settings", headers=headers)
    assert "Языки генерации" in page.text


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


def test_admin_ui_active_prompt_version_shows_diff_from_previous(client, admin_user, clean_db):
    headers = _auth_headers(client, admin_user)
    from db.enums import PromptVersionStatus
    from db.models import PromptVersion

    previous = PromptVersion(template="keep\nold line", status=PromptVersionStatus.RETIRED)
    active = PromptVersion(template="keep\nnew line", status=PromptVersionStatus.ACTIVE)
    clean_db.add_all([previous, active])
    clean_db.commit()

    page = client.get("/ui/admin/prompt-versions", headers=headers)

    assert page.status_code == 200
    assert "Изменения относительно предыдущей версии" in page.text
    assert "-old line" in page.text
    assert "+new line" in page.text
