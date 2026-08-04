from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

# In-memory pub/sub, one `api` instance (ТЗ §4.15, §6.3 — "Redis не нужен
# в MVP"). Postgres `DraftLock` (libs/db/models.py) is the actual source
# of truth for who's editing — this hub only fans out presence updates to
# connected browsers; a restart just drops connections, it never
# corrupts lock state.


@dataclass
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    display_name: str


@dataclass
class _Hub:
    # draft_id -> connection_id -> Connection
    rooms: dict[uuid.UUID, dict[int, Connection]] = field(default_factory=dict)

    def join(self, draft_id: uuid.UUID, conn: Connection) -> None:
        self.rooms.setdefault(draft_id, {})[id(conn.websocket)] = conn

    def leave(self, draft_id: uuid.UUID, websocket: WebSocket) -> None:
        room = self.rooms.get(draft_id)
        if room is None:
            return
        room.pop(id(websocket), None)
        if not room:
            self.rooms.pop(draft_id, None)

    def viewers(self, draft_id: uuid.UUID) -> list[Connection]:
        return list(self.rooms.get(draft_id, {}).values())

    async def broadcast_presence(self, draft_id: uuid.UUID, payload: dict) -> None:
        for conn in self.viewers(draft_id):
            try:
                await conn.websocket.send_json(payload)
            except Exception:  # noqa: BLE001 — a dead socket shouldn't break the broadcast for others
                pass


hub = _Hub()
