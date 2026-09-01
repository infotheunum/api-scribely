"""add draft_export_log for theunum integration

Revision ID: a1b2c3d4e5f6
Revises: bd8c1fb1b825
Create Date: 2026-09-01 16:35:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "bd8c1fb1b825"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_export_log",
        sa.Column("draft_id", sa.UUID(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("theunum_reference_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["draft.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("draft_id"),
    )


def downgrade() -> None:
    op.drop_table("draft_export_log")
