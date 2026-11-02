"""Seed 60 synthetic visible messages/tool pairs, then exercise real Gemini summary/context."""

import asyncio
import json
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
assert os.environ.get("NEXUS_LIVE_PREPUBLICATION") == "true"
os.environ["DATABASE_URL"] = (
    str(dotenv_values(ROOT / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
os.environ["DATA_DIR"] = str(ROOT / ".data/e2e")
sys.path.insert(0, str(ROOT / "apps/api"))
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from nexus.agent import build_graph  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Conversation, Message, Run, User, now  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

LEDGER = ROOT / "artifacts/prepublication/results.json"


def stopped():
    return bool(json.loads(LEDGER.read_text(encoding="utf-8")).get("halt"))


async def guarded_run(run, saver, store):
    assert not stopped()
    task = asyncio.create_task(process_run(run, "context-live-worker", saver, store))
    while not task.done():
        if stopped():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise SystemExit(75)
        await asyncio.sleep(0.2)
    await task
    with transaction() as db:
        assert db.get(Run, run.id).status == "completed", (
            "Controlled live context run failed; inspect safe run error."
        )


async def main():
    assert not stopped() and settings.ai_provider == "gemini" and settings.free_only
    user_id = sys.argv[1]
    previous = []
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-context-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(user_id=user.id, title="Long context verification")
        db.add(thread)
        db.flush()
        thread_id = thread.id
        started = now() - timedelta(minutes=60)
        for index in range(30):
            special = "The special word is GARDEN-SILVER-47. " if index == 1 else ""
            human = HumanMessage(
                content=f"Context turn {index:02d}. {special}" + "background " * 600,
                id=f"past-human-{index}",
            )
            final = AIMessage(
                content=f"Context acknowledgement {index:02d}. " + "details " * 600,
                id=f"past-final-{index}",
            )
            previous.extend(
                [
                    human,
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": f"past-call-{index}",
                                "name": "calculator",
                                "args": {"expression": "1+1"},
                            }
                        ],
                        id=f"past-request-{index}",
                    ),
                    ToolMessage(
                        content="2", tool_call_id=f"past-call-{index}", id=f"past-tool-{index}"
                    ),
                    final,
                ]
            )
            for offset, (role, message) in enumerate([("user", human), ("assistant", final)]):
                db.add(
                    Message(
                        user_id=user.id,
                        conversation_id=thread.id,
                        role=role,
                        content=str(message.content),
                        created_at=started + timedelta(seconds=index * 2 + offset),
                    )
                )
        question = "What was the special word in message 3? If it is no longer available, say you are unsure. Also use the calculator to compute 12*(3+4)."
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
    async with resources() as (saver, store):
        graph = build_graph(saver, store)
        await graph.aupdate_state(
            {"configurable": {"thread_id": thread_id}}, {"messages": previous}
        )
        claimed = claim_run("context-live-worker")
        assert claimed and claimed.id == run.id
        await guarded_run(claimed, saver, store)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        assert snapshot.values.get("summary")
        assert len(snapshot.values["messages"]) < len(previous)
        with transaction() as db:
            visible = db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == thread_id)
            )
            assert visible == 62
            final = db.scalar(
                select(Message).where(Message.run_id == run.id, Message.role == "assistant")
            )
            assert "84" in final.content
        with transaction() as db:
            fresh = Conversation(user_id=user_id, title="Independent context verification")
            db.add(fresh)
            db.flush()
            fresh_id = fresh.id
            question = "What was the special word from my other conversation? If you cannot access that context, say so."
            fresh_run = Run(
                user_id=user_id,
                conversation_id=fresh.id,
                input={"message": question, "mode": "auto"},
            )
            db.add(fresh_run)
            db.flush()
            db.add(
                Message(
                    user_id=user_id,
                    conversation_id=fresh.id,
                    run_id=fresh_run.id,
                    role="user",
                    content=question,
                )
            )
        claimed = claim_run("context-live-worker")
        assert claimed and claimed.id == fresh_run.id
        await guarded_run(claimed, saver, store)
        with transaction() as db:
            answer = db.scalar(
                select(Message).where(Message.run_id == fresh_run.id, Message.role == "assistant")
            )
            assert "GARDEN-SILVER-47" not in answer.content
        result = {
            "thread_id": thread_id,
            "new_thread_id": fresh_id,
            "seed_visible_messages": 60,
            "visible_after_summary": visible,
            "checkpoint_messages_after_pruning": len(snapshot.values["messages"]),
            "summary_present": True,
            "real_model": True,
            "seeded_history": True,
            "new_thread_inherited_old_word": False,
        }
        (ROOT / "artifacts/prepublication/CTX-live.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(
        level=logging.INFO,
        filename=ROOT / ".data/logs/prepublication-live.err.log",
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
