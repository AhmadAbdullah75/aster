"""Restart only disposable Docker PostgreSQL and verify the first real memory HTTP read."""

import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
with httpx.Client(
    base_url="http://localhost:3002", headers={"Origin": "http://localhost:3002"}, timeout=30
) as client:
    result = client.post(
        "/api/auth/login",
        json={
            "email": "publication-docker-20261025@example.com",
            "password": "synthetic-docker-password",
        },
    )
    assert result.status_code == 200
    client.cookies.set("nexus_session", result.cookies.get("nexus_session"))
    assert client.get("/api/memories").status_code == 200
    subprocess.run(
        ["docker", "restart", "nexus-publication-postgres-1"], check=True, capture_output=True
    )
    deadline = time.monotonic() + 45
    while True:
        ready = subprocess.run(
            [
                "docker",
                "exec",
                "nexus-publication-postgres-1",
                "pg_isready",
                "-U",
                "nexus_publication",
                "-d",
                "nexus_publication",
            ],
            capture_output=True,
        )
        if ready.returncode == 0:
            break
        assert time.monotonic() < deadline
        time.sleep(0.5)
    checks = []
    for route in ["/api/memories", "/api/tasks", "/api/notes", "/api/projects"]:
        started = time.monotonic()
        response = client.get(route)
        checks.append(
            {
                "route": route,
                "status": response.status_code,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
        assert response.status_code == 200, checks
    assert len(client.get("/api/memories").json()) == 1
(ROOT / "artifacts/prepublication/postgres-restart-http.json").write_text(
    json.dumps(
        {
            "first_memory_read_no_retry": True,
            "checks": checks,
            "scope": "Isolated Docker stack; real HTTP proxy/API/store; native owner database untouched.",
        },
        indent=2,
    )
    + "\n"
)
print(json.dumps(checks))
