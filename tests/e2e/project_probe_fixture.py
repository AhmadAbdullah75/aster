"""Read owned synthetic project/file/checkpoint cleanup boundaries in nexus_e2e."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- initialize isolated environment
from nexus.config import settings
from nexus.db import transaction
from nexus.memory import TransactionalStore, list_memories
from nexus.models import Chunk, Conversation, Document, IngestionJob, Note, Project, Run, Task, User
from sqlalchemy import func, select, text


async def main():
    user_id, project_id, thread_id, doc_id = sys.argv[1:5]
    blob = sys.argv[5] if len(sys.argv) > 5 else None
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-upload-projects-")
            and user.email.endswith("@example.com")
        )
        doc = db.get(Document, doc_id)
        if doc:
            assert doc.user_id == user_id and doc.project_id == project_id
            blob = doc.blob
        rows = {"projects": int(db.get(Project, project_id) is not None)}
        for name, model in [
            ("conversations", Conversation),
            ("tasks", Task),
            ("notes", Note),
            ("documents", Document),
        ]:
            rows[name] = db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == project_id, model.user_id == user_id)
            )
        rows["chunks"] = db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
        )
        rows["jobs"] = db.scalar(
            select(func.count()).select_from(IngestionJob).where(IngestionJob.document_id == doc_id)
        )
        rows["runs"] = db.scalar(
            select(func.count()).select_from(Run).where(Run.conversation_id == thread_id)
        )
        rows["memories"] = len(
            [
                memory
                for memory in await list_memories(TransactionalStore(db), user_id)
                if memory.get("project_id") == project_id
            ]
        )
        checkpoints = {
            table: db.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id=:thread"), {"thread": thread_id}
            )
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
        }
    assert blob and "/" not in blob and "\\" not in blob
    path = (settings.blobs / blob).resolve()
    assert path.is_relative_to(settings.blobs.resolve())
    print(
        json.dumps(
            {"rows": rows, "checkpoints": checkpoints, "blob": blob, "blob_exists": path.is_file()}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
