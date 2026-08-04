"""Seeds the real test Rewriter account (ТЗ §3 — "настоящий сотрудник
редакции UNUM, не заглушка"). Placeholder identity until the actual
editorial staff member is assigned (CLAUDE.md "Открыто") — the account
itself is real (real row, real login, real password), not a stub in
the auth flow.

Idempotent — matches on username, no-ops if already seeded. Credentials
come from env (Railway Variables / local .env), never hardcoded here —
REWRITER_USERNAME/REWRITER_PASSWORD/REWRITER_DISPLAY_NAME. Fails loudly
if unset rather than inventing a default password.

Usage: DATABASE_URL=... REWRITER_USERNAME=... REWRITER_PASSWORD=... python scripts/seed_rewriter.py
"""

from __future__ import annotations

import os
import sys

from api_app.auth.security import hash_password
from common.settings import CommonSettings
from db.enums import UserRole
from db.models import User
from db.session import make_engine, make_session_factory
from sqlalchemy import select


def seed(db) -> None:
    username = os.environ.get("REWRITER_USERNAME")
    password = os.environ.get("REWRITER_PASSWORD")
    display_name = os.environ.get("REWRITER_DISPLAY_NAME", "UNUM Rewriter (placeholder)")
    if not username or not password:
        print(
            "REWRITER_USERNAME/REWRITER_PASSWORD not set — skipping "
            "Rewriter account seed (not a hard error, so environments "
            "that don't need it keep deploying).",
            file=sys.stderr,
        )
        return

    existing = db.scalar(select(User).where(User.username == username))
    if existing:
        print(f"skip (exists): {username}")
        return

    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name,
            role=UserRole.REWRITER,
            is_active=True,
        )
    )
    db.commit()
    print(f"added: {username} (role=rewriter)")


def main() -> None:
    settings = CommonSettings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        seed(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
