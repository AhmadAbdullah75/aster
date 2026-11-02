"""Prepared read-only metadata probe for synthetic combined browser workflows."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- isolated database and blank provider credentials
from nexus.config import settings
from nexus.db import transaction
from nexus.memory import TransactionalStore, list_memories
from nexus.models import Chunk, Conversation, Document, Note, Project, Proposal, Run, Task, User
from sqlalchemy import select, text


async def main():
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, sys.argv[1])
        assert user and user.email.startswith(
            ("publication-flow-", "publication-history-ops-flow-")
        )
        assert user.email.endswith("@example.com")
        result = {}
        for model in (Project, Conversation, Document, Chunk, Proposal, Run, Task, Note):
            result[model.__tablename__] = [
                row.id for row in db.scalars(select(model).where(model.user_id == user.id))
            ]
        result["memories"] = [
            row["id"] for row in await list_memories(TransactionalStore(db), user.id)
        ]
        result["files"] = []
        for doc in db.scalars(select(Document).where(Document.user_id == user.id)):
            original = (settings.blobs / doc.blob).resolve()
            assert original.is_relative_to(settings.blobs.resolve())
            result["files"].append(
                {
                    "blob": doc.blob,
                    "exists": original.is_file(),
                    "bytes": original.stat().st_size if original.is_file() else 0,
                }
            )
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
