"""draft: content_generated_at for export freshness filter

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "draft",
        sa.Column(
            "content_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE draft SET content_generated_at = updated_at WHERE content_generated_at IS NULL"
        )
    )
    op.alter_column(
        "draft",
        "content_generated_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("draft", "content_generated_at")
