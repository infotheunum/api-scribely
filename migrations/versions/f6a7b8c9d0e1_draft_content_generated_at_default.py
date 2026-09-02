"""draft.content_generated_at: add Postgres server_default

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-02

Prod hit NotNullViolation on INSERT: SQLAlchemy omitted the column because
the ORM mapped server_default=func.now(), but the live column had no DEFAULT
(migration d4e5 only backfilled + set NOT NULL).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "draft",
        "content_generated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "draft",
        "content_generated_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )
