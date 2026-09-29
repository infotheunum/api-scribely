"""seed dedup LLM-confirm cost controls

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from __future__ import annotations

from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_setting (key, value, description) VALUES
        (
            'dedup.llm_confirm_enabled',
            'false'::jsonb,
            'When false, borderline embedding matches create a new cluster without ConfirmDuplicate LLM calls. Default false (token cost).'
        ),
        (
            'dedup.confirmation_threshold',
            '0.82'::jsonb,
            'Minimum cosine similarity to consider LLM confirm (when enabled). Raised from 0.45 to cut confirm volume.'
        ),
        (
            'dedup.max_confirmation_candidates',
            '1'::jsonb,
            'Max borderline candidates to ConfirmDuplicate per raw_item (1–3). Default 1.'
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app_setting WHERE key IN (
            'dedup.llm_confirm_enabled',
            'dedup.confirmation_threshold',
            'dedup.max_confirmation_candidates'
        )
        """
    )
