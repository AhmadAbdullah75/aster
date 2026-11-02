"""Record only the known synthetic publication account's canonical evidence."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.memory import TransactionalStore, list_memories  # noqa: E402
from nexus.models import Conversation, Document, Message, Note, Proposal, Run, RunEvent, Task, User  # noqa: E402
from sqlalchemy import select  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case")
    parser.add_argument("thread")
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--no-pending", action="store_true")
    parser.add_argument("--only-source-filename")
    parser.add_argument(
        "--account",
        choices=[
            "nexus-smoke-publication-20261024a@example.com",
            "nexus-empty-publication-20261024a@example.com",
        ],
        default="nexus-smoke-publication-20261024a@example.com",
    )
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Z]+-\d+", args.case)
    with transaction() as db:
        user = db.scalar(select(User).where(User.email == args.account))
        assert user
        memories = asyncio.run(list_memories(TransactionalStore(db), user.id))
        thread = db.get(Conversation, args.thread)
        assert thread and thread.user_id == user.id
        tasks = list(db.scalars(select(Task).where(Task.user_id == user.id)))
        proposals = list(db.scalars(select(Proposal).where(Proposal.conversation_id == thread.id)))
        runs = list(
            db.scalars(select(Run).where(Run.conversation_id == thread.id).order_by(Run.created_at))
        )
        messages = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == thread.id)
                .order_by(Message.created_at)
            )
        )
        events = list(
            db.scalars(
                select(RunEvent)
                .where(
                    RunEvent.run_id.in_([run.id for run in runs]), RunEvent.type != "message.delta"
                )
                .order_by(RunEvent.run_id, RunEvent.seq)
            )
        )
        if args.expected_tasks is not None:
            assert len(tasks) == args.expected_tasks, "Unexpected synthetic task count"
        if args.no_pending:
            assert not any(item.status in {"pending", "approved"} for item in proposals)
        if args.only_source_filename:
            sources = [event.payload for event in events if event.type == "source.added"]
            assert sources and all(
                item.get("filename") == args.only_source_filename for item in sources
            ), "Retrieval escaped the selected synthetic source"
        result = {
            "case": args.case,
            "thread": thread.id,
            "project_id": thread.project_id,
            "task_count": len(tasks),
            "tasks": [
                {
                    "id": item.id,
                    "title": item.title,
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "status": item.status,
                    "priority": item.priority,
                }
                for item in tasks
            ],
            "document_count": len(
                list(db.scalars(select(Document).where(Document.user_id == user.id)))
            ),
            "note_count": len(list(db.scalars(select(Note).where(Note.user_id == user.id)))),
            "memory_count": len(memories),
            "memories": [
                {
                    key: memory.get(key)
                    for key in ("id", "title", "enabled", "category", "project_id", "provenance")
                }
                for memory in memories
            ],
            "runs": [
                {"id": item.id, "status": item.status, "error": item.error, "input": item.input}
                for item in runs
            ],
            "proposals": [
                {
                    "id": item.id,
                    "status": item.status,
                    "action": item.action,
                    "item_count": len(item.payload.get("items", [])),
                    "approved": item.decision.get("approve") if item.decision else None,
                    "reviewed_items": [
                        {key: value.get(key) for key in ("id", "title", "due_date", "include")}
                        for value in (item.decision or {})
                        .get("payload", item.payload)
                        .get("items", [])
                    ],
                }
                for item in proposals
            ],
            "messages": [
                {"role": item.role, "content": item.content, "interrupted": item.interrupted}
                for item in messages
            ],
            "events": [
                {"run_id": item.run_id, "seq": item.seq, "type": item.type, "payload": item.payload}
                for item in events
            ],
        }
    target = ROOT / "artifacts/prepublication" / f"{args.case}.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{args.case}: synthetic task count {len(tasks)}; evidence saved; no secrets read or printed."
    )


if __name__ == "__main__":
    main()
