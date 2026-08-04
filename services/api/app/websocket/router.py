from __future__ import annotations

import uuid

from api_app.auth.dependencies import extract_token
from api_app.auth.security import decode_access_token
from api_app.db import new_session
from api_app.settings import ApiSettings
from api_app.websocket.lock_manager import (
    LockHeldByAnother,
    claim_editing,
    current_editor,
    heartbeat,
    release,
)
from api_app.websocket.presence import Connection, hub
from db.models import User
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _authenticate_ws(websocket: WebSocket) -> User | None:
    """`_extract_token` only reads `.headers`/`.cookies` — both present
    on Starlette's WebSocket (same HTTPConnection base as Request), so
    the same cookie the browser UI sets on login authenticates the
    socket too, no separate WS auth handshake needed."""
    settings = ApiSettings()
    token = extract_token(websocket)
    if not token:
        return None
    try:
        payload = decode_access_token(
            token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        user_id = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001
        return None
    db = new_session()
    try:
        user = db.get(User, user_id)
        return user if user and user.is_active else None
    finally:
        db.close()


async def _broadcast_room_state(draft_id: uuid.UUID) -> None:
    db = new_session()
    try:
        editor = current_editor(db, draft_id)
    finally:
        db.close()
    viewers = hub.viewers(draft_id)
    payload = {
        "type": "presence",
        "viewer_count": len(viewers),
        "viewers": [v.display_name for v in viewers],
        "editor": editor.display_name if editor else None,
        "editor_id": str(editor.id) if editor else None,
    }
    await hub.broadcast_presence(draft_id, payload)


@router.websocket("/ui/ws/drafts/{draft_id}")
async def draft_presence_ws(websocket: WebSocket, draft_id: uuid.UUID):
    """In-memory pub/sub, single `api` instance (ТЗ §4.15 — no Redis in
    MVP). Postgres `DraftLock` stays the source of truth for who holds
    the editing lock; this socket only fans out presence to viewers of
    this one draft."""
    user = _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    conn = Connection(websocket=websocket, user_id=user.id, display_name=user.display_name)
    hub.join(draft_id, conn)
    await _broadcast_room_state(draft_id)

    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")
            db = new_session()
            try:
                if action == "claim_editing":
                    try:
                        claim_editing(db, draft_id, user)
                    except LockHeldByAnother:
                        await websocket.send_json({"type": "claim_denied"})
                elif action == "release_editing":
                    release(db, draft_id, user)
                elif action == "heartbeat":
                    heartbeat(db, draft_id, user)
            finally:
                db.close()
            await _broadcast_room_state(draft_id)
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(draft_id, websocket)
        db = new_session()
        try:
            release(db, draft_id, user)
        finally:
            db.close()
        await _broadcast_room_state(draft_id)
