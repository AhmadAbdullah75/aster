"""Actual authorized tools and graph with deterministic model steering, isolated test DB only."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- initializes isolated DB, blank keys and module path
from langchain_core.messages import AIMessageChunk, ToolMessage
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Conversation, Message, Note, Project, Run, RunEvent, Task, User
from nexus.worker import claim_run, process_run
from sqlalchemy import select, text


async def main():
    scenario, user_id = sys.argv[1:3]
    assert scenario in {"calculator", "read", "project", "budget"}
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-tools-")
            and user.email.endswith("@example.com")
        )
        project_id = None
        if scenario in {"read", "project"}:
            a, b = (
                Project(user_id=user.id, title="Tool project A"),
                Project(user_id=user.id, title="Tool project B"),
            )
            db.add_all([a, b])
            db.flush()
            for index in range(25):
                db.add(
                    Task(
                        user_id=user.id,
                        project_id=a.id if index < 12 else b.id,
                        title=f"{'A' if index < 12 else 'B'} task {index:02d}",
                    )
                )
            db.add_all(
                [
                    Note(
                        user_id=user.id,
                        project_id=a.id,
                        title="Reader marker A",
                        content="Reader marker A " + "a" * 9990,
                    ),
                    Note(
                        user_id=user.id,
                        project_id=b.id,
                        title="Reader marker B",
                        content="Reader marker B private other project",
                    ),
                ]
            )
            project_id = a.id if scenario == "project" else None
        thread = Conversation(
            user_id=user.id, project_id=project_id, title="Tool boundary " + scenario
        )
        db.add(thread)
        db.flush()
        question = "Exercise the requested read tools without saving anything."
        run = Run(
            user_id=user.id, conversation_id=thread.id, input={"message": question, "mode": "auto"}
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
        first = True

        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            if self.first:
                self.first = False
                if scenario in {"read", "project"}:
                    calls = [
                        {"id": "tasks", "name": "list_tasks", "args": {}},
                        {"id": "notes", "name": "search_notes", "args": {"query": "Reader marker"}},
                    ]
                else:
                    expressions = (
                        [
                            "2340*0.15",
                            "__import__('os').system('ls')",
                            "1/0",
                            "9**9**9",
                            "letters",
                            "",
                            "1+" * 101 + "1",
                        ]
                        if scenario == "calculator"
                        else ["1+1"] * 13
                    )
                    calls = [
                        {
                            "id": f"calc-{i}",
                            "name": "calculator",
                            "args": {"expression": expression},
                        }
                        for i, expression in enumerate(expressions)
                    ]
                yield AIMessageChunk(content="", tool_calls=calls)
                return
            results = [
                json.loads(message.content)
                for message in messages
                if isinstance(message, ToolMessage)
            ]
            if scenario == "calculator":
                assert results[0]["result"] == 351
                assert len(results) == 7 and all(
                    result.get("error") and result.get("success") is False for result in results[1:]
                )
                answer = "15% of 2,340 is351. All six unsafe/invalid expressions were rejected by the calculator; no command was executed and no changes were saved."
            else:
                tasks, notes = results
                assert len(tasks["items"]) == 10 and "bounded" in tasks["notice"]
                assert max(len(note["content"]) for note in notes["items"]) == 2000
                if scenario == "project":
                    assert all(item["title"].startswith("A task") for item in tasks["items"])
                    assert [note["title"] for note in notes["items"]] == ["Reader marker A"]
                answer = (
                    "Partial task list:10items, more may exist.\n"
                    + "\n".join(item["title"] for item in tasks["items"])
                    + "\nNotes: "
                    + ", ".join(note["title"] for note in notes["items"])
                    + ". Note bodies bounded to2,000characters."
                )
            yield AIMessageChunk(content=answer)

    async with resources() as (saver, store):
        claimed = claim_run("tools-worker")
        assert claimed and claimed.id == run.id
        await process_run(claimed, "tools-worker", saver, store, Provider())
    with transaction() as db:
        result = db.get(Run, run.id)
        assert result.status == ("failed" if scenario == "budget" else "completed"), result.error
        events = list(
            db.scalars(
                select(RunEvent)
                .where(
                    RunEvent.run_id == run.id, RunEvent.type.in_(["tool.started", "tool.completed"])
                )
                .order_by(RunEvent.seq)
            )
        )
        count = 12 if scenario == "budget" else 7 if scenario == "calculator" else 2
        assert len(events) == count * 2
        assert [event.type for event in events] == ["tool.started", "tool.completed"] * count
        for i in range(0, len(events), 2):
            assert events[i].payload["call_id"] == events[i + 1].payload["call_id"]
        error = result.error
    print(
        json.dumps(
            {"thread_id": thread.id, "tool_calls": count, "serial_pairs": True, "error": error}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
