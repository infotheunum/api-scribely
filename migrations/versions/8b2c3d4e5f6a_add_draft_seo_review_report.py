"""add draft seo review report

Revision ID: 8b2c3d4e5f6a
Revises: 7a1b2c3d4e5f6
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "8b2c3d4e5f6a"
down_revision = "7a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "draft",
        sa.Column(
            "seo_review_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("draft", "seo_review_report")
