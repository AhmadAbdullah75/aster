"""Test-only deterministic provider driving the real graph and isolated e2e PostgreSQL.

Never imported by normal API/worker execution. No fixture route exists in the application.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
url = str(dotenv_values(root / ".env")["DATABASE_URL"])
os.environ["DATABASE_URL"] = url.rsplit("/", 1)[0] + "/nexus_e2e"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "gemini"
os.environ["DATA_DIR"] = str(root / ".data" / "e2e")
sys.path.insert(0, str(root / "apps" / "api"))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import AIMessageChunk  # noqa: E402
from nexus import documents  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Chunk, Conversation, Document, Message, Run, User  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402


class FixtureProvider:
    def __init__(self, responses):
        self.responses = responses

    def bind_tools(self, *args, **kwargs):
        return self

    async def astream(self, messages):
        yield AIMessageChunk(**self.responses.pop(0))
        if len(sys.argv) > 3 and sys.argv[1] == "resume" and sys.argv[3] == "slow":
            await asyncio.sleep(30)


async def fake_embed(texts):
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def main():
    if sys.argv[1] == "seed":
        action = sys.argv[3] if len(sys.argv) > 3 else "tasks.create"
        items = (
            [
                {"title": "Confirm scope", "priority": "high", "due_date": "2030-01-02"},
                {"title": "Review launch", "due_date": "2030-01-10"},
            ]
            if action.startswith("tasks")
            else [
                {"title": "Confirm scope", "content": "Audit approved content"},
                {"title": "Review launch", "content": "Audit secondary content"},
            ]
        )
        if len(sys.argv) > 4:
            items = json.loads(sys.argv[4])
        with transaction() as db:
            user = db.get(User, sys.argv[2])
            assert user, "Synthetic test user must exist"
            thread = Conversation(user_id=user.id, title="Synthetic proposal review")
            db.add(thread)
            db.flush()
            doc = Document(
                user_id=user.id,
                filename="Synthetic proposal.md",
                blob="test-only.md",
                sha256=thread.id,
                size=20,
                media_type="text/markdown",
                status="ready",
                embedding_model=documents.settings.embedding_model,
                embedding_dimensions=1536,
            )
            db.add(doc)
            db.flush()
            chunk = Chunk(
                user_id=user.id,
                document_id=doc.id,
                position=0,
                section="Launch",
                content="Discovery confirms scope. Delivery milestone launches the synthetic portal after review.",
                embedding=(await fake_embed([""]))[0],
            )
            db.add(chunk)
            db.flush()
            source_id = chunk.id
            run = Run(
                user_id=user.id,
                conversation_id=thread.id,
                input={
                    "message": "Explain this proposal and propose tasks",
                    "document_ids": [doc.id],
                },
            )
            db.add(run)
            db.flush()
            db.add(
                Message(
                    user_id=user.id,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="user",
                    content="Explain this proposal and propose tasks.",
                )
            )
            thread_id = thread.id
        documents.embed = fake_embed
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "search",
                        "name": "search_documents",
                        "args": {"query": "milestones", "coverage": True},
                    }
                ],
            },
            {
                "content": f"Discovery confirms scope; delivery follows review. [source:{source_id}]\n\n```python\nprint('Ready for review')\n```\n",
                "tool_calls": [
                    {
                        "id": "create",
                        "name": "propose_action",
                        "args": {
                            "action": action,
                            "payload": {"items": items},
                        },
                    }
                ],
            },
        ]
    else:
        thread_id = sys.argv[2]
        content = "Your approved selection has been saved exactly once."
        if len(sys.argv) > 3 and sys.argv[3] == "slow":
            content += " These committed tasks remain saved if generation is stopped."
        responses = [{"content": content}]
    async with resources() as (saver, store):
        run = claim_run("e2e-worker")
        assert run and run.conversation_id == thread_id
        await process_run(run, "e2e-worker", saver, store, FixtureProvider(responses))
    print(thread_id)


if __name__ == "__main__":
    asyncio.run(main())
