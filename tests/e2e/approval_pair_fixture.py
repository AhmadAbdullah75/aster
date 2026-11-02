"""Seed two real pending proposals (20+1 items) through the isolated graph."""

import asyncio
import json
import sys

import graph_fixture as fixture
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Conversation, Message, Run, User
from nexus.worker import claim_run, process_run
from sqlalchemy import text


async def main():
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, sys.argv[1])
        assert (
            user
            and user.email.startswith("publication-approval-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(user_id=user.id, title="Review21tasks in two batches")
        db.add(thread)
        db.flush()
        query = "Create21tasks in reviewable batches of at most20items."
        run = Run(user_id=user.id, conversation_id=thread.id, input={"message": query})
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user.id,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=query,
            )
        )
    calls = [
        {
            "id": f"batch-{index}",
            "name": "propose_action",
            "args": {
                "action": "tasks.create",
                "payload": {
                    "items": [
                        {"title": f"Batch{index} task{number:02d}"} for number in range(count)
                    ]
                },
            },
        }
        for index, count in enumerate([20, 1])
    ]
    async with resources() as (saver, store):
        claimed = claim_run("approval-pair-worker")
        assert claimed and claimed.id == run.id
        await process_run(
            claimed,
            "approval-pair-worker",
            saver,
            store,
            fixture.FixtureProvider(
                [{"content": "Review the two batches before saving.", "tool_calls": calls}]
            ),
        )
    print(json.dumps({"thread_id": thread.id}))


if __name__ == "__main__":
    asyncio.run(main())
