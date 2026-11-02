"""Read-only integrity probe for a synthetic interrupted browser upload."""

import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(ROOT / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
os.environ["DATA_DIR"] = str(ROOT / ".data/e2e")
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.models import Document, IngestionJob, User  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    user = db.get(User, sys.argv[1])
    assert user and user.email.startswith("publication-upload-cancel-")
    assert user.email.endswith("@example.com")
    docs = list(db.scalars(select(Document).where(Document.user_id == user.id)))
    jobs = list(db.scalars(select(IngestionJob).join(Document).where(Document.user_id == user.id)))
    assert len(docs) == len(jobs) and len(docs) <= 1
    blobs = []
    for doc in docs:
        assert doc.filename == "closed-tab.txt" and doc.size == 1024 * 1024
        assert doc.status == "queued"
        job = next(job for job in jobs if job.document_id == doc.id)
        assert job.status == "queued"
        original = (settings.blobs / doc.blob).resolve()
        assert original.is_relative_to(settings.blobs.resolve())
        data = original.read_bytes()
        assert data == b"A" * (1024 * 1024)
        assert hashlib.sha256(data).hexdigest() == doc.sha256
        blobs.append(doc.blob)
    print(json.dumps({"documents": len(docs), "jobs": len(jobs), "complete_blobs": blobs,
                      "half_created_records": 0, "complete_bytes_verified": bool(docs)}))
