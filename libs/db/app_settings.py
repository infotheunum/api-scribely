from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from db.models import AppSetting


def get_setting(db: Session, key: str, default: Any) -> Any:
    """Reads a tuning knob fresh from Postgres on every call (ТЗ §4.21) —
    no in-process cache, so an Admin API edit takes effect on the very
    next scheduler tick/gRPC call, not after a restart. Falls back to
    `default` when the row hasn't been seeded yet, so every call site
    keeps working before Admin Settings is ever touched."""
    row = db.get(AppSetting, key)
    return row.value if row is not None else default


def set_setting(
    db: Session,
    key: str,
    value: Any,
    *,
    description: str | None = None,
    updated_by: uuid.UUID | None = None,
) -> AppSetting:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    if description is not None:
        row.description = description
    row.updated_by = updated_by
    return row
