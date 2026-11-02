"""Pause an actual scoped retrieval before SQL lookup, allowing browser deletion."""

import asyncio
import json
import sys

import graph_fixture as fixture
from langchain_core.messages import AIMessageChunk
from nexus import documents
from nexus.config import ROOT, settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Chunk, Conversation, Document, Message, Run, User, uid
from nexus.worker import claim_run, process_run
from sqlalchemy import text


async def main():
    identity = sys.argv[1]
    marker = ROOT / "artifacts/prepublication" / f"search-deletion-{identity}.json"
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, identity)
        assert (
            user
            and user.email.startswith("publication-integrity-")
            and user.email.endswith("@example.com")
        )
        blob = uid() + ".txt"
        settings.blobs.mkdir(parents=True, exist_ok=True)
        (settings.blobs / blob).write_text("Acceptance owner is Lina.", encoding="utf-8")
        doc = Document(
            user_id=identity,
            filename="Search deletion evidence.txt",
            blob=blob,
            sha256=uid(),
            size=25,
            media_type="text/plain",
            status="ready",
            embedding_model=settings.embedding_model,
            embedding_dimensions=1536,
        )
        db.add(doc)
        db.flush()
        db.add(
            Chunk(
                user_id=identity,
                document_id=doc.id,
                position=0,
                section="Evidence",
                content="Acceptance owner is Lina.",
                embedding=[1.0] + [0.0] * 1535,
            )
        )
        thread = Conversation(user_id=identity, title="Deletion during document search")
        db.add(thread)
        db.flush()
        run = Run(
            user_id=identity,
            conversation_id=thread.id,
            input={
                "message": "Who owns acceptance?",
                "mode": "documents",
                "document_ids": [doc.id],
            },
        )
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=identity,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=run.input["message"],
            )
        )
    data = {"thread_id": thread.id, "document_id": doc.id, "search_started": False}
    marker.write_text(json.dumps(data))

    async def embedding(texts):
        data["search_started"] = True
        marker.write_text(json.dumps(data))
        await asyncio.sleep(12)
        return await fixture.fake_embed(texts)

    documents.embed = embedding

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            evidence = json.loads(messages[-1].content)
            assert evidence["sources"] == [], "Deleted document leaked into a new search result"
            yield AIMessageChunk(
                content="The document was removed. No current evidence is available to verify the owner."
            )

    async with resources() as (saver, store):
        claimed = claim_run("search-deletion-worker")
        assert claimed and claimed.id == run.id
        await process_run(claimed, "search-deletion-worker", saver, store, Provider())
    assert not (settings.blobs / blob).exists()


if __name__ == "__main__":
    asyncio.run(main())
