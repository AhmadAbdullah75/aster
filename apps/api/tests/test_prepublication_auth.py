"""Additional cases from the owner's pre-publication plan, in isolated nexus_test."""

from datetime import timedelta

import pytest
from conftest import register
from fastapi.testclient import TestClient
from nexus.config import settings
from nexus.db import transaction
from nexus.main import app
from nexus.models import RateBucket, Run, Session, User, now
from sqlalchemy import func, select


@pytest.mark.parametrize(
    "case_id,changes,status",
    [
        ("AUTH-02", {"password": "123456789"}, 422),
        ("AUTH-03", {"password": "1234567890"}, 200),
        ("AUTH-06-abc", {"email": "abc"}, 422),
        ("AUTH-06-a-at", {"email": "a@"}, 422),
        ("AUTH-06-at-b", {"email": "@b.com"}, 422),
        ("AUTH-06-space", {"email": "a b@c.com"}, 422),
        ("AUTH-07-empty", {"name": ""}, 422),
        ("AUTH-07-space", {"name": "   "}, 422),
        ("AUTH-08-long", {"name": "a" * 1000}, 422),
        ("AUTH-08-emoji", {"name": "Mira 🌿"}, 200),
        ("AUTH-08-urdu", {"name": "احمد"}, 200),
        ("AUTH-11", {"is_admin": True}, 422),
    ],
)
def test_registration_boundaries(client, case_id, changes, status):
    payload = {"email": "publication@example.com", "password": "synthetic-password", "name": "Mira"}
    result = client.post("/auth/register", json={**payload, **changes})
    assert result.status_code == status, (case_id, result.text)
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(User)) == (1 if status == 200 else 0)


def test_AUTH_04_AUTH_05_AUTH_10_duplicate_case_and_hash(client):
    register(client, "Alice@example.com")
    for email in ("alice@example.com", "ALICE@EXAMPLE.COM"):
        result = client.post(
            "/auth/register", json={"email": email, "password": "synthetic-test-password"}
        )
        assert result.status_code == 409
        assert "already exists" in result.json()["detail"]
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert "synthetic-test-password" not in user.password_hash


@pytest.mark.parametrize("password", ["spaces inside a password", "اردو پاس ورڈ 🌿", "p" * 200])
def test_AUTH_09_extended_password_login(client, password):
    credentials = {"email": "password@example.com", "password": password}
    assert client.post("/auth/register", json=credentials).status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.post("/auth/login", json=credentials).status_code == 200


def test_LOG_02_LOG_03_LOG_04_LOG_08_LOG_10(client):
    register(client)
    cookie = client.cookies.get("nexus_session")
    bad = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
    )
    unknown = client.post(
        "/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    with TestClient(app, headers={"origin": settings.app_origin}) as other:
        login = other.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "synthetic-test-password"},
        )
        assert login.status_code == 200
        header = login.headers["set-cookie"].lower()
        assert all(part in header for part in ("httponly", "samesite=lax", "path=/", "max-age="))
        assert client.post("/auth/logout").status_code == 200
        client.cookies.set("nexus_session", cookie)
        assert client.get("/me").status_code == 401
        assert other.get("/me").status_code == 200


def test_SES_01_SES_03_SES_04(client):
    register(client)
    with transaction() as db:
        for session in db.scalars(select(Session)):
            session.expires_at = now() - timedelta(seconds=1)
    assert client.get("/me").status_code == 401
    client.cookies.clear()
    client.cookies.set("nexus_session", "random-tampered-cookie")
    assert client.get("/me").status_code == 401
    assert (
        client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "synthetic-test-password"},
        ).status_code
        == 200
    )
    assert client.get("/me").status_code == 200


def test_RL_01_login_threshold_and_cooldown(client, monkeypatch):
    from nexus import security

    register(client)
    statuses = [
        client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
        ).status_code
        for _ in range(30)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429] * 20
    original_time = security.time.time
    monkeypatch.setattr(security.time, "time", lambda: original_time() + 301)
    assert (
        client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "synthetic-test-password"},
        ).status_code
        == 200
    )


def test_RL_02_register_threshold(client):
    results = [
        client.post(
            "/auth/register",
            json={"email": f"rate-{i}@example.com", "password": "synthetic-rate-password"},
        ).status_code
        for i in range(9)
    ]
    assert results[:8] == [200] * 8
    assert results[-1] == 429
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 8
        assert db.scalar(select(func.count()).select_from(RateBucket)) >= 1


def test_RL_03_expensive_operations_are_limited(client, monkeypatch):
    register(client)
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-unused-key-no-provider-called")
    for index in range(16):
        thread = client.post("/conversations", json={}).json()
        response = client.post(
            f"/conversations/{thread['id']}/runs",
            json={"message": "No worker is running in this isolated API test."},
        )
        assert response.status_code == (202 if index < 15 else 429)
        if response.status_code == 202:
            with transaction() as db:
                db.get(Run, response.json()["id"]).status = "completed"
    for index in range(11):
        response = client.post(
            "/documents",
            files={
                "file": (
                    "rate.txt",
                    b"Synthetic indexing is not started in this test.",
                    "text/plain",
                )
            },
        )
        assert response.status_code == (202 if index < 10 else 429)
