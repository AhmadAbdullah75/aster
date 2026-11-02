"""Presentation-only synthetic fixtures, using real isolated tables and the official memory store."""

import asyncio
import json
import sys
from datetime import datetime

import graph_fixture  # noqa: F401 -- isolated environment and blank provider keys
from nexus.db import transaction
from nexus.memory import TransactionalStore, namespace
from nexus.models import Conversation, Message, Note, Project, Run, Task, User, now, uid
from sqlalchemy import text


async def main():
    mode, identity = sys.argv[1:3]
    assert mode in {"bulk", "markdown", "branding", "message_growth"}
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, identity)
        assert (
            user
            and user.email.startswith("publication-presentation-")
            and user.email.endswith("@example.com")
        )
        if mode == "message_growth":
            before = db.scalar(text("SELECT pg_total_relation_size('messages')"))
            for index in range(500):
                thread = Conversation(user_id=identity, title=f"Growth sample{index}")
                db.add(thread)
                db.flush()
                for role in ["user", "assistant"]:
                    db.add(
                        Message(
                            user_id=identity,
                            conversation_id=thread.id,
                            role=role,
                            content=f"Synthetic {role} message{index} for storage measurement.",
                        )
                    )
            db.flush()
            after = db.scalar(text("SELECT pg_total_relation_size('messages')"))
            count, row_bytes = db.execute(
                text("SELECT count(*),sum(pg_column_size(m)) FROM messages m WHERE user_id=:user"),
                {"user": identity},
            ).one()
            assert count == 1000
            result = {
                "messages": count,
                "conversations": 500,
                "owned_projection_row_bytes": row_bytes,
                "shared_table_allocation_before_bytes": before,
                "shared_table_allocation_after_bytes": after,
                "allocation_delta_bytes": after - before,
                "scope": "1000actual message projections; graph/event/checkpoint growth is measured separately. Shared table allocation may reuse existing pages.",
            }
        elif mode in {"markdown", "branding"}:
            if mode == "branding":
                user.timezone = "Asia/Karachi"
            thread = Conversation(user_id=identity, title="A place for your next idea" if mode == "branding" else "Long content " + "R" * 187)
            db.add(thread)
            db.flush()
            run = Run(user_id=identity, conversation_id=thread.id, status="completed", input={})
            db.add(run)
            db.flush()
            markdown = (
                "# Layout evidence\n\n"
                + "LONGWORD" * 200
                + "\n\n<https://example.com/"
                + "longpath/" * 250
                + ">\n\n```javascript\nconst evidence = '"
                + "code" * 500
                + "';\n```\n\n"
            )
            markdown += "|" + "|".join(f"Column{n}" for n in range(50)) + "|\n"
            markdown += "|" + "|".join("---" for _ in range(50)) + "|\n"
            markdown += "|" + "|".join("Wide table evidence" for _ in range(50)) + "|\n"
            if mode == "branding":
                markdown = "## A little clarity for your next step\n\nStart with one idea. We can explore it together, connect it to your documents, and turn it into a plan you review.\n\n**Your workspace, at your pace.**"
            db.add(
                Message(
                    user_id=identity,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="user",
                    content="Help me make room for my next good idea." if mode == "branding" else "Show synthetic layout evidence.",
                    created_at=datetime.fromisoformat("2026-10-26T23:59:08+00:00") if mode == "branding" else now(),
                )
            )
            db.add(
                Message(
                    user_id=identity,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="assistant",
                    content=markdown,
                    created_at=datetime.fromisoformat("2026-10-27T00:00:12+00:00") if mode == "branding" else now(),
                )
            )
            result = {
                "thread_id": thread.id,
                "source": "Synthetic presentation data; no provider call",
            }
        else:
            project = Project(user_id=identity, title="Bulk scope")
            db.add(project)
            db.flush()
            for index in range(205):
                thread = Conversation(user_id=identity, title=f"Bulk chat{index:03d}")
                db.add(thread)
                db.flush()
                db.add(
                    Message(
                        user_id=identity,
                        conversation_id=thread.id,
                        role="user",
                        content=f"Bulk question{index}",
                    )
                )
                db.add(
                    Message(
                        user_id=identity,
                        conversation_id=thread.id,
                        role="assistant",
                        content=f"Bulk saved answer{index}",
                    )
                )
            db.add_all(
                [
                    Task(
                        user_id=identity,
                        project_id=project.id if index % 2 else None,
                        title=f"Bulk task{index:03d}",
                        status=["todo", "in_progress", "done"][index % 3],
                        priority=["low", "medium", "high"][index % 3],
                    )
                    for index in range(150)
                ]
            )
            db.add(
                Note(
                    user_id=identity,
                    title="Bulk note",
                    content="A combined-account navigation check.",
                )
            )
            store = TransactionalStore(db)
            for index in range(101):
                await store.aput(
                    namespace(identity),
                    uid(),
                    {
                        "title": f"Bulk memory{index:03d}",
                        "content": f"Synthetic bulk preference{index}",
                        "category": "preference",
                        "enabled": True,
                        "project_id": None,
                        "version": 1,
                        "created_at": now().isoformat(),
                        "updated_at": now().isoformat(),
                        "provenance": "Synthetic combined-account fixture",
                    },
                )
            result = {
                "conversations": 205,
                "tasks": 150,
                "memories": 101,
                "projects": 1,
                "notes": 1,
            }
    print(json.dumps(result))


asyncio.run(main())
