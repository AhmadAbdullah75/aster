"""Seed/verify synthetic recovery data inside the isolated publication containers."""

import asyncio
import hashlib
import json
import sys

from langchain_core.messages import AIMessageChunk
from nexus.agent import build_graph
from nexus.config import settings
from nexus.db import transaction
from nexus.documents import parse
from nexus.graph_resources import resources
from nexus.memory import TransactionalStore, list_memories, save_memory
from nexus.models import Chunk, Conversation, Document, Message, Note, Run, Task, User, uid
from nexus.schemas import MemoryInput
from nexus.worker import claim_run, process_run
from sqlalchemy import func, select, text

EMAIL = "publication-docker-20261025@example.com"
DATA = b"Recovery evidence: acceptance owner is Lina. Original storage must survive restoration."


async def main():
    mode = sys.argv[1]
    assert mode in {"seed", "verify", "missing-files"}
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) in {
            "nexus_publication",
            "nexus_restore",
        }
        user = db.scalar(select(User).where(User.email == EMAIL))
        assert user, "Create the synthetic Docker account in the browser first"
        if mode == "seed":
            assert not db.scalar(select(Conversation).where(Conversation.user_id == user.id))
            doc = Document(
                user_id=user.id,
                filename="Recovery evidence.txt",
                blob=uid() + ".txt",
                sha256=hashlib.sha256(DATA).hexdigest(),
                size=len(DATA),
                media_type="text/plain",
                status="ready",
                embedding_model=settings.embedding_model,
                embedding_dimensions=1536,
            )
            settings.blobs.mkdir(parents=True, exist_ok=True)
            (settings.blobs / doc.blob).write_bytes(DATA)
            db.add(doc)
            db.flush()
            for item in parse(DATA, ".txt"):
                db.add(
                    Chunk(
                        user_id=user.id, document_id=doc.id, embedding=[1.0] + [0.0] * 1535, **item
                    )
                )
            db.add(Task(user_id=user.id, title="Recovery task"))
            db.add(
                Note(user_id=user.id, title="Recovery note", content="Synthetic recovery content.")
            )
            await save_memory(
                TransactionalStore(db),
                user.id,
                MemoryInput(title="Recovery preference", content="Use concise recovery reports."),
            )
            thread = Conversation(user_id=user.id, title="Recovery checkpoint")
            db.add(thread)
            db.flush()
            run = Run(
                user_id=user.id,
                conversation_id=thread.id,
                input={"message": "Verify recovery preference", "mode": "auto"},
            )
            db.add(run)
            db.flush()
            db.add(
                Message(
                    user_id=user.id,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="user",
                    content=run.input["message"],
                )
            )

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            yield AIMessageChunk(content="Recovery checkpoint and memory verified.")

    async with resources() as (saver, store):
        if mode == "seed":
            claimed = claim_run("recovery-probe")
            assert claimed and claimed.id == run.id
            await process_run(claimed, "recovery-probe", saver, store, Provider())
        with transaction() as db:
            thread = db.scalar(select(Conversation).where(Conversation.user_id == user.id))
            doc = db.scalar(select(Document).where(Document.user_id == user.id))
            assert thread and doc
            assert (
                db.scalar(select(func.count()).select_from(Task).where(Task.user_id == user.id))
                == 1
            )
            assert (
                db.scalar(select(func.count()).select_from(Note).where(Note.user_id == user.id))
                == 1
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.conversation_id == thread.id)
                )
                == 2
            )
            assert (
                db.scalar(select(Chunk).where(Chunk.document_id == doc.id)).content == DATA.decode()
            )
        memories = await list_memories(store, user.id)
        assert len(memories) == 1 and memories[0]["content"] == "Use concise recovery reports."
        state = await build_graph(saver, store).aget_state(
            {"configurable": {"thread_id": thread.id}}
        )
        assert len(state.values["messages"]) == 2
        assert state.values["messages"][-1].content == "Recovery checkpoint and memory verified."
        exists = (settings.blobs / doc.blob).is_file()
        if mode == "missing-files":
            assert not exists
        else:
            assert (
                hashlib.sha256((settings.blobs / doc.blob).read_bytes()).hexdigest() == doc.sha256
            )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "thread_id": thread.id,
                    "document_id": doc.id,
                    "original_exists": exists,
                    "checkpoint_messages": 2,
                    "memories": len(memories),
                    "tasks": 1,
                    "notes": 1,
                    "source_chunk_valid": True,
                }
            )
        )


asyncio.run(main())
