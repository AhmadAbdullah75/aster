"""Inspect the actual model-facing memory selection with a deterministic isolated provider."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- initialize isolated database and blank provider keys
from langchain_core.messages import AIMessageChunk
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Conversation, Message, Run, RunEvent, User
from nexus.worker import claim_run, process_run
from sqlalchemy import select, text


async def main():
    user_id, project_id, expected_json = sys.argv[1:4]
    expected = json.loads(expected_json)
    project_id = None if project_id == "-" else project_id
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-collection-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(
            user_id=user_id, project_id=project_id, title="Memory selection verification"
        )
        db.add(thread)
        db.flush()
        query = "Give a brief garden overview."
        run = Run(user_id=user_id, conversation_id=thread.id, input={"message": query})
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user_id,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=query,
            )
        )
    seen = []

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            values = json.JSONDecoder().raw_decode(
                str(messages[0].content).split("Current saved memories: ", 1)[1]
            )[0]
            seen.extend(value["id"] for value in values)
            if isinstance(expected, int):
                assert len(values) == expected
            else:
                assert set(seen) == set(expected)
            yield AIMessageChunk(
                content="Synthetic overview. Only the authorized current memory selection was supplied. "
                + " ".join(value["content"] for value in values)
            )

    async with resources() as (saver, store):
        claimed = claim_run("memory-context-worker")
        assert claimed and claimed.id == run.id
        await process_run(claimed, "memory-context-worker", saver, store, Provider())
    with transaction() as db:
        assert db.get(Run, run.id).status == "completed", db.get(Run, run.id).error
        events = list(
            db.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.type == "memory.used")
            )
        )
        ids = [item["id"] for event in events for item in event.payload["items"]]
        assert set(ids) == set(seen)
    print(json.dumps({"thread_id": thread.id, "selected_ids": seen, "memory_event_ids": ids}))


if __name__ == "__main__":
    asyncio.run(main())
