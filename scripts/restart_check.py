"""Verify documented Windows stop/start retains an authenticated synthetic workspace."""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
email = f"nexus-smoke-{int(time.time() * 1000)}@example.com"
with httpx.Client(
    base_url="http://127.0.0.1:3000/api", headers={"Origin": "http://127.0.0.1:3000"}, timeout=30
) as client:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "synthetic-restart-password",
            "name": "Synthetic Restart",
        },
    )
    response.raise_for_status()
    user = response.json()
    project = client.post("/projects", json={"title": "Synthetic restart project"}).json()
    note = client.post(
        "/notes",
        json={
            "title": "Durable restart note",
            "content": "Retain this synthetic content.",
            "project_id": project["id"],
        },
    ).json()
    client.post(
        "/memories",
        json={
            "title": "Restart preference",
            "content": "Use simple English",
            "project_id": project["id"],
        },
    ).raise_for_status()
    try:
        subprocess.run(["pwsh", "-File", str(root / "scripts/stop.ps1")], cwd=root, check=True)
        subprocess.run(
            ["pwsh", "-File", str(root / "scripts/start.ps1"), "-SkipBuild"], cwd=root, check=True
        )
        assert client.get("/me").json()["id"] == user["id"]
        assert client.get("/notes/" + note["id"]).json()["content"] == note["content"]
        assert any(m["title"] == "Restart preference" for m in client.get("/memories").json())
        (root / "artifacts/restart.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "checks": [
                        "documented stop/start",
                        "session persists",
                        "notes persist",
                        "LangGraph project store persists",
                    ],
                },
                indent=2,
            )
        )
        print("Native stop/start passed: session, note and store memory retained.")
    finally:
        response = client.delete(f"/projects/{project['id']}?version={project['version']}")
        response.raise_for_status()
        subprocess.run(
            [sys.executable, str(root / "scripts/cleanup_smoke.py"), user["id"], email],
            cwd=root,
            check=True,
        )
