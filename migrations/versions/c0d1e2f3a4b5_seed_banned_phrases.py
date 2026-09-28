"""seed compliance.banned_phrases for rewrite filter 5

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None

_BANNED = [
    {"phrase": "следите", "category": "investment"},
    {"phrase": "требует внимания", "category": "investment"},
    {"phrase": "может предвещать", "category": "investment"},
    {"phrase": "buy now", "category": "investment"},
    {"phrase": "стоит купить", "category": "investment"},
    {"phrase": "важный", "category": "evaluation"},
    {"phrase": "важная", "category": "evaluation"},
    {"phrase": "важное", "category": "evaluation"},
    {"phrase": "значительный", "category": "evaluation"},
    {"phrase": "значительная", "category": "evaluation"},
    {"phrase": "впечатляющий", "category": "evaluation"},
    {"phrase": "впечатляющая", "category": "evaluation"},
    {"phrase": "колоссальный", "category": "evaluation"},
    {"phrase": "беспрецедентный", "category": "evaluation"},
    {"phrase": "ошеломляющий", "category": "evaluation"},
    {"phrase": "поразительный", "category": "evaluation"},
    {"phrase": "может привести", "category": "forecast"},
    {"phrase": "ожидается", "category": "forecast"},
    {"phrase": "эксперты ожидают", "category": "forecast"},
    {"phrase": "в рамках", "category": "bureaucracy"},
    {"phrase": "данный", "category": "bureaucracy"},
    {"phrase": "данная", "category": "bureaucracy"},
    {"phrase": "данное", "category": "bureaucracy"},
    {"phrase": "таким образом", "category": "bureaucracy"},
    {"phrase": "имеет место быть", "category": "bureaucracy"},
    {"phrase": "на сегодняшний день", "category": "bureaucracy"},
    {"phrase": "в настоящее время", "category": "bureaucracy"},
    {"phrase": "следует отметить", "category": "bureaucracy"},
    {"phrase": "важно отметить", "category": "bureaucracy"},
    {"phrase": "стоит подчеркнуть", "category": "bureaucracy"},
    {"phrase": "нельзя не сказать", "category": "bureaucracy"},
    {"phrase": "подводя итог", "category": "bureaucracy"},
    {"phrase": "в заключение", "category": "bureaucracy"},
    {"phrase": "лендинг", "category": "bad_translation"},
    {"phrase": "кредитный etf", "category": "bad_translation"},
    {"phrase": "кредитный ETF", "category": "bad_translation"},
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            INSERT INTO app_setting (key, value, description)
            VALUES (
                'compliance.banned_phrases',
                CAST(:value AS jsonb),
                'Phrase blacklist for rewrite filter 5 '
                '(investment/evaluation/forecast/bureaucracy/bad_translation).'
            )
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {"value": json.dumps(_BANNED, ensure_ascii=False)},
    )


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM app_setting WHERE key = 'compliance.banned_phrases'"))
