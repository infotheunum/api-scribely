"""seed llm.enabled_providers AppSetting (openai-only default)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
"""

from __future__ import annotations

from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_setting (key, value, description)
        VALUES (
            'llm.enabled_providers',
            '["openai"]'::jsonb,
            'Primary LLM slots for article enrichment/rewrite/dedup confirmation — JSON array of qwen/openai/anthropic. Default ["openai"]. Round-robin runs only among enabled slots that have API keys in env.'
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_setting WHERE key = 'llm.enabled_providers'")
