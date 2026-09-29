"""enable balanced dedup LLM-confirm defaults (0.85, on)

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from __future__ import annotations

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Force the balanced profile even if e2f3 already seeded false/0.82.
    op.execute(
        """
        INSERT INTO app_setting (key, value, description) VALUES
        (
            'dedup.llm_confirm_enabled',
            'true'::jsonb,
            'When true, borderline embedding matches get one ConfirmDuplicate LLM call. Default true with high threshold (0.85).'
        ),
        (
            'dedup.confirmation_threshold',
            '0.85'::jsonb,
            'Minimum cosine similarity for LLM confirm. 0.85 keeps quality without the old 0.45×3 spend.'
        ),
        (
            'dedup.max_confirmation_candidates',
            '1'::jsonb,
            'Max ConfirmDuplicate candidates per raw_item (1–3). Default 1.'
        )
        ON CONFLICT (key) DO UPDATE
          SET value = EXCLUDED.value,
              description = EXCLUDED.description
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_setting SET value = 'false'::jsonb
          WHERE key = 'dedup.llm_confirm_enabled';
        UPDATE app_setting SET value = '0.82'::jsonb
          WHERE key = 'dedup.confirmation_threshold';
        """
    )
