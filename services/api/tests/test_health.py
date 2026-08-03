from __future__ import annotations


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "X-Trace-Id" in resp.headers


def test_health_rewrite_unreachable_returns_503(client):
    # No rewrite server is running at REWRITE_GRPC_ADDRESS in this test —
    # confirms the endpoint fails loudly instead of reporting false health.
    resp = client.get("/health/rewrite")
    assert resp.status_code == 503
