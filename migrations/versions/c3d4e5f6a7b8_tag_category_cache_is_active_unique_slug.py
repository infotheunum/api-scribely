"""tag_category_cache: is_active + unique (kind, slug) for theunum sync

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tag_category_cache",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "uq_tag_category_cache_kind_slug",
        "tag_category_cache",
        ["kind", "slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tag_category_cache_kind_slug", table_name="tag_category_cache")
    op.drop_column("tag_category_cache", "is_active")
