from __future__ import annotations

import os

os.environ.setdefault("REWRITE_GRPC_ADDRESS", "localhost:50098")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-service-token")

from fastapi.testclient import TestClient  # noqa: E402
from worker_app.main import app  # noqa: E402


def test_health_ok():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert "X-Trace-Id" in resp.headers


def test_health_rewrite_unreachable_returns_503():
    with TestClient(app) as client:
        resp = client.get("/health/rewrite")
        assert resp.status_code == 503
