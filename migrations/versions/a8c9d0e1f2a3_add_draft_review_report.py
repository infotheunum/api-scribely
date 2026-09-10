"""store the source-grounded editorial review with a draft

Revision ID: a8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "a8c9d0e1f2a3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "draft",
        sa.Column(
            "review_report",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("draft", "review_report")
