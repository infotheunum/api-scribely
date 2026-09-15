"""persistent cluster quarantine and pre-rewrite exclusion context

Revision ID: 7a1b2c3d4e5f
Revises: a8c9d0e1f2a3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7a1b2c3d4e5f"
down_revision = "a8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_setting (key, value, description)
        VALUES ('quality_gate.enabled', 'true'::jsonb,
                'LLM factual and editorial verification before a draft enters review.')
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.add_column(
        "cluster_context",
        sa.Column("political_core", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "cluster_context",
        sa.Column("promotional_or_partner", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("cluster_context", sa.Column("exclusion_evidence", sa.Text(), nullable=True))
    op.create_table(
        "cluster_quarantine",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cluster_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["news_cluster.id"]),
        sa.ForeignKeyConstraint(["released_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id"),
    )


def downgrade() -> None:
    op.drop_table("cluster_quarantine")
    op.drop_column("cluster_context", "exclusion_evidence")
    op.drop_column("cluster_context", "promotional_or_partner")
    op.drop_column("cluster_context", "political_core")
