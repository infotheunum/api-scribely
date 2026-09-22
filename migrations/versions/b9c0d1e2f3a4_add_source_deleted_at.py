"""add source.deleted_at for admin soft-delete

Revision ID: b9c0d1e2f3a4
Revises: 8b2c3d4e5f6a
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "8b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_source_deleted_at", "source", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_source_deleted_at", table_name="source")
    op.drop_column("source", "deleted_at")
