"""Real isolated proposal lifecycle; crash mode exits only this test subprocess after commit."""

import asyncio
import json
import os
import sys
import time

import graph_fixture as fixture
from nexus.actions import execute
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import AuditEvent, Conversation, Message, Project, Proposal, Run, Task, User, now
from nexus.worker import claim_run, process_run, recover
from sqlalchemy import func, select, text


async def main():
    mode, user_id = sys.argv[1:3]
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-approval-")
            and user.email.endswith("@example.com")
        )
    if mode == "deleted-check":
        thread_id = sys.argv[3]
        with transaction() as db:
            assert db.get(Conversation, thread_id) is None
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                assert (
                    db.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE thread_id=:thread"),
                        {"thread": thread_id},
                    )
                    == 0
                )
        print(json.dumps({"deleted_graph_rows": 0}))
        return
    if mode in {"crash", "replay"}:
        thread_id = sys.argv[3]
        with transaction() as db:
            thread = db.get(Conversation, thread_id)
            assert thread and thread.user_id == user_id
            proposal = db.scalar(select(Proposal).where(Proposal.conversation_id == thread_id))
            assert proposal and proposal.user_id == user_id
            proposal_id = proposal.id
        if mode == "crash":
            run = claim_run("postcommit-crash")
            assert run and run.conversation_id == thread_id
            result = await execute(None, user_id, proposal_id)
            assert len(result["saved"]) == 2
            print(json.dumps({"committed": True, "checkpoint_not_resumed": True}), flush=True)
            os._exit(91)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            with transaction() as db:
                run = db.get(Run, proposal.run_id)
                expired = run.lease_until < now()
            if expired:
                break
            time.sleep(0.1)
        assert expired
        recover()
        result = await execute(None, user_id, proposal_id)
        with transaction() as db:
            assert (
                db.scalar(select(func.count()).select_from(Task).where(Task.user_id == user_id))
                == 2
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.resource_id == proposal_id,
                        AuditEvent.action == "proposal.executed",
                    )
                )
                == 1
            )
            assert db.get(Run, proposal.run_id).status == "failed"
        print(
            json.dumps(
                {"saved_count": len(result["saved"]), "known_outcome": True, "duplicates": False}
            )
        )
        return
    assert mode in {"project", "memory-off"}
    with transaction() as db:
        project = None
        if mode == "project":
            project = Project(user_id=user_id, title="Publication pending project")
            db.add(project)
            db.flush()
        else:
            assert not db.get(User, user_id).memory_enabled
        thread = Conversation(
            user_id=user_id,
            project_id=project.id if project else None,
            title="Approval lifecycle " + mode,
        )
        db.add(thread)
        db.flush()
        query = (
            "Create one task in this project."
            if project
            else "Remember that I prefer brief answers."
        )
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
        item = (
            {"title": "Scoped pending task", "project_id": project.id}
            if project
            else {"title": "Brief answers", "content": "I prefer brief answers"}
        )
        action = "tasks.create" if project else "memories.create"
    responses = [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "lifecycle",
                    "name": "propose_action",
                    "args": {"action": action, "payload": {"items": [item]}},
                }
            ],
        }
    ]
    if mode == "memory-off":
        responses += [{"content": "Memory is disabled. No memory was saved."}] * 2
    async with resources() as (saver, store):
        claimed = claim_run("lifecycle-worker")
        assert claimed and claimed.id == run.id
        await process_run(
            claimed, "lifecycle-worker", saver, store, fixture.FixtureProvider(responses)
        )
    with transaction() as db:
        proposal = db.scalar(select(Proposal).where(Proposal.run_id == run.id))
        assert (proposal is not None) == bool(project)
    print(
        json.dumps(
            {
                "thread_id": thread.id,
                "project_id": project.id if project else None,
                "proposal_id": proposal.id if proposal else None,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
