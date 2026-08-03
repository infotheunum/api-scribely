from __future__ import annotations

import os
import uuid

import pytest

# Point at the throwaway dev Postgres used to verify migrations (see
# scripts/gen_proto.sh sibling docs) — must be set before api_app.main is
# imported anywhere, since ApiSettings() reads env at instantiation time.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:55432/unum_news"
)
os.environ.setdefault("REWRITE_GRPC_ADDRESS", "localhost:50099")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-service-token")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from api_app.auth.security import hash_password  # noqa: E402
from api_app.db import _session_factory  # noqa: E402
from api_app.main import app  # noqa: E402
from db.models import User  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user():
    session = _session_factory()()
    user = User(
        id=uuid.uuid4(),
        username=f"rewriter-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("correct-horse-battery-staple"),
        display_name="Test Rewriter",
        role="rewriter",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield user
    finally:
        session.delete(user)
        session.commit()
        session.close()
