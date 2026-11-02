"""Owned synthetic transcript only, strictly confined to the isolated browser database."""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(root / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import Conversation, Message, Proposal, Run, RunEvent, User  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

if sys.argv[1] == "counts":
    thread_id = sys.argv[2]
    with transaction() as db:
        run_ids = select(Run.id).where(Run.conversation_id == thread_id)
        counts = {
            "conversations": db.scalar(
                select(func.count()).select_from(Conversation).where(Conversation.id == thread_id)
            ),
            "messages": db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == thread_id)
            ),
            "runs": db.scalar(
                select(func.count()).select_from(Run).where(Run.conversation_id == thread_id)
            ),
            "events": db.scalar(
                select(func.count()).select_from(RunEvent).where(RunEvent.run_id.in_(run_ids))
            ),
            "proposals": db.scalar(
                select(func.count())
                .select_from(Proposal)
                .where(Proposal.conversation_id == thread_id)
            ),
        }
        for table in ["checkpoints", "checkpoint_blobs", "checkpoint_writes"]:
            counts[table] = db.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id=:thread"), {"thread": thread_id}
            )
    print(json.dumps(counts))
    raise SystemExit(0)

assert sys.argv[1] in {"bulk", "pending"}
with transaction() as db:
    user = db.get(User, sys.argv[2])
    assert (
        user
        and user.email.startswith("publication-history-")
        and user.email.endswith("@example.com")
    )
    thread = Conversation(
        user_id=user.id,
        title="Long transcript" if sys.argv[1] == "bulk" else "Pending deletion review",
    )
    db.add(thread)
    db.flush()
    thread_id = thread.id
    for number in range(110 if sys.argv[1] == "bulk" else 1):
        run = Run(user_id=user.id, conversation_id=thread.id, status="completed", input={})
        db.add(run)
        db.flush()
        for role, index in [("user", number * 2), ("assistant", number * 2 + 1)]:
            db.add(
                Message(
                    user_id=user.id,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role=role,
                    content=f"History turn {index:03d}",
                )
            )
    if sys.argv[1] == "pending":
        run.status = "queued"
        run.input = {"message": "Create one synthetic task", "mode": "auto"}

if sys.argv[1] == "pending":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    from langchain_core.messages import AIMessageChunk
    from nexus.graph_resources import resources
    from nexus.worker import claim_run, process_run

    class ProposalProvider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            yield AIMessageChunk(
                content="",
                tool_calls=[
                    {
                        "name": "propose_action",
                        "id": "delete-review-call",
                        "args": {
                            "action": "tasks.create",
                            "payload": {
                                "items": [{"title": "Must never be written after deletion"}]
                            },
                        },
                    }
                ],
            )

    async def pending():
        run = claim_run("publication-delete-worker")
        assert run and run.conversation_id == thread_id
        async with resources() as (saver, store):
            await process_run(run, "publication-delete-worker", saver, store, ProposalProvider())

    asyncio.run(pending())
print(thread_id)
