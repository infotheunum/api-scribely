from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/unum_news"
)
os.environ.setdefault("REWRITE_GRPC_ADDRESS", "localhost:50098")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-service-token")

import pytest  # noqa: E402
from db.models import NewsCluster, RawItem, Source  # noqa: E402
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


def _wipe(session):
    # RawItem first — it FKs both Source and NewsCluster, so it has to
    # go before either of them.
    session.execute(delete(RawItem))
    session.execute(delete(Source))
    session.execute(delete(NewsCluster))
    session.commit()


@pytest.fixture
def clean_db(db):
    """Some tests need a real, empty slate for Source/RawItem uniqueness
    checks to be meaningful. Wiped both before AND after — tests in this
    file commit real rows (not just an in-transaction state a rollback
    would undo), so without a teardown wipe they leak into whatever else
    queries this same local dev database next (including a manually
    started `worker` process, which will happily start polling
    `https://example.com/feed` forever)."""
    _wipe(db)
    yield db
    _wipe(db)
