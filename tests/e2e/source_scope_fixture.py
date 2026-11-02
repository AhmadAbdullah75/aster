"""Synthetic ready/processing/failed metadata for UI boundaries; isolated DB, no embeddings."""

import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(root / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import Document, User  # noqa: E402
from sqlalchemy import text  # noqa: E402

with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    user = db.get(User, sys.argv[2])
    assert (
        user and user.email.startswith("publication-scope-") and user.email.endswith("@example.com")
    )
    if sys.argv[1] == "seed":
        docs = []
        for index in range(31):
            doc = Document(
                user_id=user.id,
                filename=f"Scope document {index:02d}.txt",
                blob=f"synthetic-scope-{index}.txt",
                sha256=f"scope-{user.id}-{index}",
                size=30,
                media_type="text/plain",
                status="ready",
            )
            db.add(doc)
            db.flush()
            docs.append({"id": doc.id, "filename": doc.filename})
        print(json.dumps(docs))
    else:
        assert sys.argv[1] in {"indexing", "failed", "ready"}
        doc = db.get(Document, sys.argv[3])
        assert doc and doc.user_id == user.id
        doc.status = sys.argv[1]
        doc.error = (
            "Synthetic extraction failure. Retry indexing." if doc.status == "failed" else None
        )
