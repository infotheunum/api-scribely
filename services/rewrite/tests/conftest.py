from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/unum_news"
)
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-service-token")

import pytest  # noqa: E402
from db.models import LLMRotationState, LLMRotationUsage, PromptVersion  # noqa: E402
from rewrite_app.db import _session_factory  # noqa: E402
from sqlalchemy import delete  # noqa: E402


@pytest.fixture
def db():
    session = _session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _wipe(session):
    session.execute(delete(LLMRotationUsage))
    session.execute(delete(LLMRotationState))
    session.execute(delete(PromptVersion))
    session.commit()


@pytest.fixture
def clean_db(db):
    _wipe(db)
    yield db
    _wipe(db)
