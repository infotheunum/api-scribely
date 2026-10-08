"""pace dispatch through the day + tighter freshness window

Revision ID: a7b8c9d0e1f2
Revises: f3a4b5c6d7e8
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "a7b8c9d0e1f2"
down_revision = "f3a4b5c6d7e8"
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
        "dispatch.target_per_hour",
        9,
        "Soft hourly draft cap so ~100/day spreads across the 06–18 window "
        "(~8–9/h) instead of burning the quota by late morning.",
    )
    _upsert(
        conn,
        "ingestion.max_item_age_hours",
        24,
        "Editorial freshness window (hours). Clusters older than this are not "
        "selected for rewrite; prefer midday fresh stories over overnight junk.",
    )


def downgrade() -> None:
    conn = op.get_bind()
    _upsert(
        conn,
        "dispatch.target_per_hour",
        18,
        "Soft hourly draft cap (legacy default).",
    )
    _upsert(
        conn,
        "ingestion.max_item_age_hours",
        48,
        "Editorial freshness window (hours) — legacy 48h default.",
    )
