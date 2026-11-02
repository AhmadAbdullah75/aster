"""Remove only the fixed synthetic account created during the 2026-10-24 browser audit."""

import sys
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))

from nexus.db import transaction  # noqa: E402
from nexus.models import User  # noqa: E402

email = "browser-audit-20261024@example.com"
with httpx.Client(
    base_url="http://127.0.0.1:8000", headers={"origin": "http://127.0.0.1:3000"}, timeout=90
) as client:
    response = client.post(
        "/auth/login", json={"email": email, "password": "Synthetic-Audit-2026!"}
    )
    response.raise_for_status()
    user = client.get("/me").json()
    assert user["email"] == email and user["name"] == "Nexus Audit"
    for kind in ("projects", "conversations", "documents"):
        while records := client.get("/" + kind).json():
            for record in records:
                deleted = client.delete(f"/{kind}/{record['id']}?version={record['version']}")
                deleted.raise_for_status()
    client.post("/memories/clear", json={}).raise_for_status()
    client.post("/auth/logout", json={}).raise_for_status()
with transaction() as db:
    record = db.get(User, user["id"])
    assert record and record.email == email
    db.delete(record)
print("Only the synthetic browser audit account, its blobs, memories and checkpoints were removed.")
