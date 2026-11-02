"""Real graph/worker/event streaming with a slow deterministic provider; isolated DB only."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(root / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
sys.path.insert(0, str(root / "apps" / "api"))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Conversation, Message, Run, User  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402


class SlowProvider:
    def bind_tools(self, *args, **kwargs):
        return self

    async def astream(self, messages):
        mode = sys.argv[3] if len(sys.argv) > 3 else "stream"
        if mode == "tool":
            yield AIMessageChunk(
                content="",
                tool_calls=[
                    {
                        "id": "slow-calculator",
                        "name": "calculator",
                        "args": {"expression": "12*(3+4)"},
                    }
                ],
            )
            return
        if mode in {"after-cancel", "fast"}:
            outstanding = set()
            for message in messages:
                if isinstance(message, AIMessage):
                    outstanding.update(call["id"] for call in message.tool_calls)
                if isinstance(message, ToolMessage):
                    outstanding.discard(message.tool_call_id)
            assert not outstanding, "Unpaired tool call would be rejected by a provider"
            yield AIMessageChunk(
                content="Recovered worker completed this fresh run."
                if mode == "fast"
                else "Follow-up after cancellation has valid tool-call history and completes successfully."
            )
            return
        if mode == "timeout":
            yield AIMessageChunk(
                content="Saved partial output before the controlled long provider wait. This text must survive the active-run timeout.\n\n"
            )
            await asyncio.sleep(400)
            return
        for number in range(150):
            yield AIMessageChunk(
                content=f"Audit stream paragraph {number:03d}. This is saved partial output for navigation and cancellation verification.\n\n"
            )
            await asyncio.sleep(0.3)


async def main():
    if sys.argv[1] == "seed":
        with transaction() as db:
            assert db.get(User, sys.argv[2])
            if len(sys.argv) > 3:
                thread = db.get(Conversation, sys.argv[3])
                assert thread and thread.user_id == sys.argv[2]
            else:
                thread = Conversation(user_id=sys.argv[2], title="Audit streaming")
                db.add(thread)
                db.flush()
            run = Run(
                user_id=sys.argv[2],
                conversation_id=thread.id,
                input={"message": "Audit long response", "mode": "auto"},
            )
            db.add(run)
            db.flush()
            db.add(
                Message(
                    user_id=sys.argv[2],
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="user",
                    content="Audit long response",
                )
            )
            print(thread.id)
        return
    run = claim_run("audit-stream-worker")
    assert run and run.conversation_id == sys.argv[2]
    if len(sys.argv) > 3 and sys.argv[3] == "tool":
        import nexus.agent as agent

        original_read = agent.read_tool

        async def slow_read(*args, **kwargs):
            await asyncio.sleep(30)
            return await original_read(*args, **kwargs)

        agent.read_tool = slow_read
    async with resources() as (saver, store):
        await process_run(run, "audit-stream-worker", saver, store, SlowProvider())


asyncio.run(main())
