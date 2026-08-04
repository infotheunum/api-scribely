"""Seeds a real test Admin account (ТЗ §4.21 — Admin Settings needs a
real login to reach, same "real row, not a stub" standard as
[[seed_rewriter]]).

Idempotent — matches on username, no-ops if already seeded. Credentials
come from env (Railway Variables / local .env), never hardcoded here —
ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_DISPLAY_NAME. Fails loudly if unset
rather than inventing a default password.

Usage: DATABASE_URL=... ADMIN_USERNAME=... ADMIN_PASSWORD=... python scripts/seed_admin.py
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
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "UNUM Admin (placeholder)")
    if not username or not password:
        print(
            "ADMIN_USERNAME/ADMIN_PASSWORD not set — skipping Admin "
            "account seed (not a hard error, so environments that "
            "don't need it keep deploying).",
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
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    db.commit()
    print(f"added: {username} (role=admin)")


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
