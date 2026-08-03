from __future__ import annotations


def test_login_success(client, test_user):
    resp = client.post(
        "/auth/login",
        data={"username": test_user.username, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password(client, test_user):
    resp = client.post(
        "/auth/login", data={"username": test_user.username, "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/auth/login", data={"username": "nobody", "password": "whatever"})
    assert resp.status_code == 401


def test_me_requires_token(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_valid_token(client, test_user):
    login_resp = client.post(
        "/auth/login",
        data={"username": test_user.username, "password": "correct-horse-battery-staple"},
    )
    token = login_resp.json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == test_user.username
    assert body["role"] == "rewriter"
