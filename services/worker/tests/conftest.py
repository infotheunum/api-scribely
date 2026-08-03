from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/unum_news"
)
os.environ.setdefault("REWRITE_GRPC_ADDRESS", "localhost:50098")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-service-token")

import pytest  # noqa: E402
from db.models import RawItem, Source  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from worker_app.db import _session_factory  # noqa: E402


@pytest.fixture
def db():
    session = _session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def clean_db(db):
    """Some tests need a real, empty slate for Source/RawItem uniqueness
    checks to be meaningful."""
    db.execute(delete(RawItem))
    db.execute(delete(Source))
    db.commit()
    yield db
    db.rollback()
