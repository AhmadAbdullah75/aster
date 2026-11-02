"""Inspect only an owned synthetic document's real isolated indexing/retrieval state."""

import asyncio
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
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus import documents  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.models import Chunk, Document, IngestionJob, User  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

action, user_id, document_id = sys.argv[1:4]
with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    user = db.get(User, user_id)
    assert (
        user
        and user.email.startswith("publication-upload-")
        and user.email.endswith("@example.com")
    )
    doc = db.get(Document, document_id)
    assert not doc or doc.user_id == user.id
    if action == "old-model":
        assert doc and doc.status == "ready"
        doc.embedding_model = "obsolete-test-model"
    counts = {
        "documents": int(doc is not None),
        "chunks": db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        ),
        "jobs": db.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.document_id == document_id)
        ),
    }
if action == "search":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    result = asyncio.run(
        documents.search(user_id, "Cedar Lantern", None, [document_id], coverage=True)
    )
    counts["search_sources"] = len(result["sources"])
else:
    assert action in {"counts", "old-model"}
print(json.dumps(counts))
