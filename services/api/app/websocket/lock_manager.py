from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from db.enums import DraftLockMode
from db.models import DraftLock, User
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# TTL/heartbeat (ТЗ §4.15) — a client refreshes this on an interval well
# under LOCK_TTL; a lock past expiry is stale (tab closed without a clean
# disconnect, laptop sleep, etc.) and treated as released.
LOCK_TTL = timedelta(minutes=5)


class LockHeldByAnother(Exception):
    def __init__(self, holder: User):
        self.holder = holder


def _purge_expired(db: Session, draft_id: uuid.UUID) -> None:
    db.execute(
        delete(DraftLock).where(
            DraftLock.draft_id == draft_id, DraftLock.expires_at < datetime.now(UTC)
        )
    )


def current_editor(db: Session, draft_id: uuid.UUID) -> User | None:
    _purge_expired(db, draft_id)
    db.commit()
    lock = db.scalar(
        select(DraftLock).where(
            DraftLock.draft_id == draft_id, DraftLock.mode == DraftLockMode.EDITING
        )
    )
    if lock is None:
        return None
    return db.get(User, lock.user_id)


def claim_editing(db: Session, draft_id: uuid.UUID, user: User) -> None:
    """Raises LockHeldByAnother if someone else already holds the
    editing lock. The DB partial unique index (one editing lock per
    draft) is the real guarantee — this is a friendly pre-check plus
    the actual write, not just the check."""
    _purge_expired(db, draft_id)
    db.commit()

    existing = db.get(DraftLock, (draft_id, user.id))
    now = datetime.now(UTC)
    if existing is not None:
        existing.mode = DraftLockMode.EDITING
        existing.heartbeat_at = now
        existing.expires_at = now + LOCK_TTL
    else:
        db.add(
            DraftLock(
                draft_id=draft_id,
                user_id=user.id,
                mode=DraftLockMode.EDITING,
                heartbeat_at=now,
                expires_at=now + LOCK_TTL,
            )
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        holder = current_editor(db, draft_id)
        raise LockHeldByAnother(holder) from exc


def heartbeat(db: Session, draft_id: uuid.UUID, user: User) -> None:
    lock = db.get(DraftLock, (draft_id, user.id))
    if lock is None or lock.mode != DraftLockMode.EDITING:
        return
    now = datetime.now(UTC)
    lock.heartbeat_at = now
    lock.expires_at = now + LOCK_TTL
    db.commit()


def release(db: Session, draft_id: uuid.UUID, user: User) -> None:
    db.execute(
        delete(DraftLock).where(DraftLock.draft_id == draft_id, DraftLock.user_id == user.id)
    )
    db.commit()
