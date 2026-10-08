"""raise weekday daily draft quota to 150 and pace ~13/h

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _upsert(conn, key: str, value, description: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO app_setting (key, value, description)
            VALUES (:key, CAST(:value AS jsonb), :description)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                description = EXCLUDED.description
            """
        ),
        {
            "key": key,
            "value": json.dumps(value),
            "description": description,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    _upsert(
        conn,
        "queue.daily_limit",
        150,
        "Max drafts created on weekdays (editorial day, Europe/Minsk).",
    )
    _upsert(
        conn,
        "dispatch.target_per_hour",
        13,
        "Soft hourly draft cap so ~150/day spreads across the 06–18 window "
        "(~12–13/h).",
    )


def downgrade() -> None:
    conn = op.get_bind()
    _upsert(
        conn,
        "queue.daily_limit",
        100,
        "Max drafts created on weekdays (legacy 100).",
    )
    _upsert(
        conn,
        "dispatch.target_per_hour",
        9,
        "Soft hourly draft cap for legacy ~100/day pace.",
    )
