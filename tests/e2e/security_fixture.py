"""Seed a hostile-text assistant projection from an actually parsed owned source in E3."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
url = str(dotenv_values(root / ".env")["DATABASE_URL"])
os.environ["DATABASE_URL"] = url.rsplit("/", 1)[0] + "/nexus_e2e"
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import Chunk, Conversation, Document, Message  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

thread_id, document_id = sys.argv[1:]
with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    thread = db.get(Conversation, thread_id)
    document = db.get(Document, document_id)
    assert thread and document and thread.user_id == document.user_id
    chunk = db.scalar(select(Chunk).where(Chunk.document_id == document_id))
    assert chunk and document.status == "ready"
    db.add(
        Message(
            user_id=thread.user_id,
            conversation_id=thread_id,
            role="assistant",
            content=f"Synthetic source quotation:\n\n{chunk.content}\n\n[source:{chunk.id}]",
            sources=[
                {
                    "id": chunk.id,
                    "document_id": document.id,
                    "filename": document.filename,
                    "section": chunk.section,
                    "excerpt": chunk.content,
                }
            ],
        )
    )
print("Isolated hostile-text projection seeded; no provider called.")
