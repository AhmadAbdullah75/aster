"""Deterministic transport, real graph/SQL, restricted to publication citation test users."""

import asyncio
import json
import sys

import graph_fixture as fixture
from langchain_core.messages import AIMessageChunk
from nexus import documents
from nexus.config import settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Chunk, Conversation, Document, Message, Run, User
from nexus.worker import claim_run, process_run
from sqlalchemy import select, text


async def main():
    scenario, user_id = sys.argv[1:3]
    assert scenario in {"invalid", "groundfail", "deleted"}
    documents.embed = fixture.fake_embed
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-citation-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(user_id=user.id, title="Citation boundary " + scenario)
        db.add(thread)
        db.flush()
        doc_id = source_id = None
        if scenario != "deleted":
            doc = Document(
                user_id=user.id,
                filename="citation-evidence.txt",
                blob="test-only-citation.txt",
                sha256=thread.id,
                size=32,
                media_type="text/plain",
                status="ready",
                embedding_model=settings.embedding_model,
                embedding_dimensions=1536,
            )
            db.add(doc)
            db.flush()
            doc_id = doc.id
            chunk = Chunk(
                user_id=user.id,
                document_id=doc.id,
                position=0,
                section="Launch",
                content="CITATION-PLUM acceptance owner is Lina.",
                embedding=(await fixture.fake_embed([""]))[0],
            )
            db.add(chunk)
            db.flush()
            source_id = chunk.id
        else:
            assert not list(db.scalars(select(Document).where(Document.user_id == user.id)))
        question = (
            "Explain this document and create one task."
            if scenario == "groundfail"
            else "Who owns CITATION-PLUM acceptance?"
        )
        run = Run(
            user_id=user.id,
            conversation_id=thread.id,
            input={"message": question, "mode": "documents"},
        )
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user.id,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=question,
            )
        )

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("Synthetic grounding outage")

        async def astream(self, messages):
            if scenario == "groundfail":
                yield AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "id": "review-task",
                            "name": "propose_action",
                            "args": {
                                "action": "tasks.create",
                                "payload": {"items": [{"title": "Review citation evidence"}]},
                            },
                        }
                    ],
                )
            elif scenario == "deleted":
                assert json.loads(messages[-1].content)["sources"] == []
                yield AIMessageChunk(
                    content="No current document evidence is available. I cannot verify the owner."
                )
            else:
                yield AIMessageChunk(
                    content=f"Acceptance owner is Lina. [source:{source_id}] Unsupported numeric reference [99]. Forged reference [source:99999999-9999-4999-8999-999999999999]."
                )

    async with resources() as (saver, store):
        claimed = claim_run("citation-worker")
        assert claimed and claimed.id == run.id
        await process_run(claimed, "citation-worker", saver, store, Provider())
    print(json.dumps({"thread_id": thread.id, "document_id": doc_id, "source_id": source_id}))


if __name__ == "__main__":
    asyncio.run(main())
