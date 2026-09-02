"""draft: llm token usage columns for theunum analytics

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "draft",
        sa.Column("llm_prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "draft",
        sa.Column("llm_completion_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "draft",
        sa.Column("llm_total_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("draft", "llm_total_tokens")
    op.drop_column("draft", "llm_completion_tokens")
    op.drop_column("draft", "llm_prompt_tokens")
