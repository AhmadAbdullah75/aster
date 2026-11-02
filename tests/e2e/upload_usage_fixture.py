"""Seed only synthetic persisted storage usage in the isolated browser database."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(ROOT / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import Document, User  # noqa: E402
from sqlalchemy import text  # noqa: E402

with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    user = db.get(User, sys.argv[1])
    assert (
        user
        and user.email.startswith("publication-upload-")
        and user.email.endswith("@example.com")
    )
    for number in range(20):
        db.add(
            Document(
                user_id=user.id,
                filename=f"Quota fixture {number}.txt",
                blob=f"quota-fixture-{number}.txt",
                sha256=f"quota-{user.id}-{number}",
                size=10 * 1024 * 1024,
                media_type="text/plain",
                status="ready",
            )
        )
print("Synthetic persisted 200 MiB usage seeded; no 200 MiB disk allocation.")
