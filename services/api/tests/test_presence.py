from __future__ import annotations

import pytest
from api_app.auth.security import create_access_token
from api_app.settings import ApiSettings
from db.enums import DraftStatus, SourceTier, SourceType
from db.models import Draft, NewsCluster, RawItem, Source
from starlette.websockets import WebSocketDisconnect


def _token_for(user) -> str:
    settings = ApiSettings()
    return create_access_token(
        user_id=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )


def _draft(db) -> Draft:
    source = Source(
        name="s",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    cluster = NewsCluster(trace_id="t")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id="item-1",
            url="https://example.com/1",
            title="Headline",
            body="Body",
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    draft = Draft(
        cluster_id=cluster.id,
        title_en="x",
        body_en="x" * 150,
        title_ru="y",
        body_ru="y" * 150,
        trace_id="t",
        status=DraftStatus.READY_FOR_REVIEW,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_ws_rejects_without_auth(client, clean_db):
    draft = _draft(clean_db)
    # Server closes immediately with 4401 — the close happens during the
    # handshake itself, so the context manager's __enter__ is what raises.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ui/ws/drafts/{draft.id}"):
            pass


def test_ws_claim_and_presence_broadcast(client, test_user, clean_db):
    draft = _draft(clean_db)
    token = _token_for(test_user)
    client.cookies.set("access_token", token)

    with client.websocket_connect(f"/ui/ws/drafts/{draft.id}") as ws:
        initial = ws.receive_json()
        assert initial["type"] == "presence"
        assert initial["viewer_count"] == 1
        assert initial["editor"] is None

        ws.send_json({"action": "claim_editing"})
        after_claim = ws.receive_json()
        assert after_claim["editor"] == test_user.display_name


def test_ws_second_editor_denied_while_first_holds_lock(client, test_user, admin_user, clean_db):
    draft = _draft(clean_db)
    client.cookies.set("access_token", _token_for(test_user))
    with client.websocket_connect(f"/ui/ws/drafts/{draft.id}") as ws1:
        ws1.receive_json()  # initial presence
        ws1.send_json({"action": "claim_editing"})
        ws1.receive_json()  # presence after claim

        # A second simultaneous session — use the Authorization header
        # (checked before the cookie) rather than the shared client's
        # cookie jar, so both "users" can be connected at once.
        admin_headers = {"Authorization": f"Bearer {_token_for(admin_user)}"}
        with client.websocket_connect(f"/ui/ws/drafts/{draft.id}", headers=admin_headers) as ws2:
            ws2.receive_json()  # initial presence (2 viewers now, broadcast to ws2)
            ws2.send_json({"action": "claim_editing"})
            denied = ws2.receive_json()
            assert denied["type"] == "claim_denied"


def test_publish_blocked_while_another_user_holds_editing_lock(
    client, test_user, admin_user, clean_db
):
    from api_app.websocket.lock_manager import claim_editing

    draft = _draft(clean_db)
    clean_db.query(Draft).filter_by(id=draft.id).update({"image_license_confirmed": True})
    clean_db.commit()
    claim_editing(clean_db, draft.id, admin_user)

    client.cookies.set("access_token", _token_for(test_user))
    resp = client.post(f"/ui/drafts/{draft.id}/publish", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]

    fresh = clean_db.get(Draft, draft.id)
    assert fresh.status == DraftStatus.READY_FOR_REVIEW  # unchanged, publish was blocked
