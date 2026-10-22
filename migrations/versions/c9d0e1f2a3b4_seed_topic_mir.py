"""seed Topic «Мир» (world/society/culture/science/…)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from __future__ import annotations

from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

# Keep in sync with DEFAULT_TOPIC_KEYWORDS["Мир"] in
# services/worker/app/filter/topics.py — runtime source of truth is the
# Topic row; this migration only bootstraps existing DBs that already
# seeded the original ten scopes.
_KEYWORDS = [
    r"\bworld\b",
    "global",
    "international",
    "abroad",
    "overseas",
    "society",
    "culture",
    r"\bart\b",
    "music",
    "cinema",
    r"\bfilm\b",
    "festival",
    "tradition",
    "lifestyle",
    "science",
    "research",
    "discovery",
    r"\bspace\b",
    "archaeology",
    "environment",
    "climate",
    "ecology",
    "disaster",
    "earthquake",
    r"\bflood\b",
    "wildfire",
    "hurricane",
    "tsunami",
    "epidemic",
    "pandemic",
    "health",
    "medicine",
    "vaccine",
    "education",
    "school",
    "university",
    "travel",
    "tourism",
    r"\bsport\b",
    "в мире",
    "за рубежом",
    "международн",
    "глобальн",
    "зарубежн",
    "иностранн",
    "обществ",
    "культур",
    "искусств",
    "музыка",
    "кино",
    "фестивал",
    "традици",
    "образ жизни",
    "наука",
    "исследован",
    "открыти",
    "космос",
    "археолог",
    "экологи",
    "климат",
    "окружающ(ая|ей) среда",
    "катастроф",
    "землетряс",
    "наводнени",
    "пожар",
    "ураган",
    "цунами",
    "эпидеми",
    "пандеми",
    "здоровь",
    "медицин",
    "вакцин",
    "образован",
    "школ",
    "университет",
    "туризм",
    "путешеств",
    "спорт",
]


def upgrade() -> None:
    # ARRAY literal — escape single quotes in patterns (none today).
    array_sql = ", ".join("'" + kw.replace("'", "''") + "'" for kw in _KEYWORDS)
    op.execute(
        f"""
        INSERT INTO topic (id, name, keywords, is_active)
        VALUES (
            gen_random_uuid(),
            'Мир',
            ARRAY[{array_sql}]::text[],
            true
        )
        ON CONFLICT (name) DO UPDATE
        SET
            keywords = EXCLUDED.keywords,
            is_active = true,
            updated_at = now()
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM topic WHERE name = 'Мир'")
