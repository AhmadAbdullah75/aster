"""Controlled provider faults drive the real graph in nexus_e2e, with no network calls."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- blank keys, isolated database and storage
from google.genai.errors import ClientError
from langchain_core.messages import AIMessageChunk
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Conversation, Message, Run, User
from nexus.worker import claim_run, process_run
from sqlalchemy import text


async def main():
    identity, scenario = sys.argv[1:3]
    assert scenario in {
        "invalid_key",
        "missing_model",
        "simulated_429",
        "empty",
        "no_chunks",
        "malformed",
        "output_limit",
    }
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, identity)
        assert (
            user
            and user.email.startswith("publication-provider-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(user_id=user.id, title=f"Controlled provider {scenario}")
        db.add(thread)
        db.flush()
        run = Run(
            user_id=user.id,
            conversation_id=thread.id,
            input={"message": "Synthetic provider failure check", "mode": "auto"},
        )
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user.id,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=run.input["message"],
            )
        )

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            if scenario in {"invalid_key", "missing_model", "simulated_429"}:
                raise ClientError(
                    {"invalid_key": 400, "missing_model": 404, "simulated_429": 429}[scenario],
                    {"error": {"message": "SYNTHETIC-SECRET-DO-NOT-DISPLAY private request"}},
                )
            if scenario == "no_chunks":
                return
            if scenario == "output_limit":
                yield AIMessageChunk(
                    content="Saved partial response. " * 1500,
                    response_metadata={"finish_reason": "MAX_TOKENS"},
                )
                return
            if scenario == "malformed":
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": "calculator", "args": "{broken", "id": "bad", "index": 0}
                    ],
                )
            else:
                yield AIMessageChunk(content="")

    async with resources() as (saver, store):
        claimed = claim_run("provider-failure-worker")
        assert claimed and claimed.id == run.id
        await process_run(claimed, "provider-failure-worker", saver, store, Provider())
    print(json.dumps({"thread_id": thread.id, "run_id": run.id}))


if __name__ == "__main__":
    asyncio.run(main())
