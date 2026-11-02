"""Prepared live-flow worker: real Gemini, disposable DB, single attempts, paced calls.

Only the explicitly enabled live suite invokes this helper.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path.cwd().resolve()
assert (ROOT / "apps/api/nexus").is_dir()
assert os.environ.get("NEXUS_LIVE_PREPUBLICATION") == "true"
env = dotenv_values(ROOT / ".env")
os.environ["DATABASE_URL"] = str(env["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
os.environ["DATA_DIR"] = str(ROOT / ".data/e2e")
os.environ["AI_PROVIDER"] = "gemini"
os.environ["FREE_ONLY"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = str(env["GEMINI_API_KEY"])
sys.path.insert(0, str(ROOT / "apps/api"))
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from nexus import provider  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Run, User  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

LEDGER = ROOT / "artifacts/prepublication/results.json"
RATE = ROOT / "artifacts/prepublication/live-flow-rate.json"


def stopped():
    state = json.loads(LEDGER.read_text(encoding="utf-8"))
    return bool(state.get("halt") or state.get("external_blocker"))


def halt_quota():
    subprocess.run(
        [
            sys.executable,
            "scripts/prepublication_results.py",
            "halt-quota",
            "--evidence",
            "Real Gemini quota/rate failure during isolated end-to-end workflow. Stop immediately; owner must update GEMINI_API_KEY directly in root .env and explicitly resume.",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


class QuotaStop(logging.Handler):
    def emit(self, record):
        if re.search(
            r"HTTP/\S+ 429\b|RESOURCE_EXHAUSTED|quota.{0,30}exceeded", record.getMessage(), re.I
        ):
            halt_quota()
            os._exit(75)


async def gate():
    last = json.loads(RATE.read_text()).get("last", 0) if RATE.exists() else 0
    while time.time() - last < 30:
        assert not stopped(), "Live testing stopped"
        await asyncio.sleep(0.2)
    assert not stopped(), "Live testing stopped"
    RATE.write_text(json.dumps({"last": time.time()}))


@asynccontextmanager
async def single_attempt_google_client():
    await gate()
    provider.require_provider()
    api = genai.Client(
        api_key=settings.gemini_api_key,
        vertexai=False,
        http_options=types.HttpOptions(
            timeout=settings.request_timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    async with api.aio as connection:
        yield connection


class PacedModel:
    def __init__(self, actual):
        self.actual = actual

    def bind_tools(self, *args, **kwargs):
        return PacedModel(self.actual.bind_tools(*args, **kwargs))

    async def astream(self, messages):
        await gate()
        async for chunk in self.actual.astream(messages):
            yield chunk

    async def ainvoke(self, messages):
        await gate()
        return await self.actual.ainvoke(messages)


@asynccontextmanager
async def paced_run_timeout():
    # Only this explicitly opted-in, disposable live helper receives an allowance
    # for its deliberate30s rate waits. Production workers retain their180s budget.
    original = settings.run_timeout_seconds
    allowance = 30 * (settings.max_tool_calls + 4)
    settings.run_timeout_seconds = original + allowance
    try:
        yield {
            "production_timeout_seconds": original,
            "pacing_allowance_seconds": allowance,
            "fixture_timeout_seconds": settings.run_timeout_seconds,
        }
    finally:
        settings.run_timeout_seconds = original


async def main():
    assert not stopped()
    settings.assert_provider_policy()
    assert settings.free_only and settings.ai_provider == "gemini" and settings.provider_key
    user_id, thread_id = sys.argv[1:3]
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith(("publication-flow-", "publication-history-ops-flow-"))
            and user.email.endswith("@example.com")
        )
        expected = db.scalar(
            select(Run).where(
                Run.conversation_id == thread_id, Run.user_id == user_id, Run.status == "queued"
            )
        )
        assert expected
    provider.google_client = single_attempt_google_client
    actual = provider.chat_model()
    # The installed adapter documents 1 as a single attempt; 0 uses SDK defaults.
    actual.max_retries = 1
    run = claim_run("publication-live-flow")
    assert run and run.id == expected.id
    async with paced_run_timeout() as timeout_scope, resources() as (saver, store):
        task = asyncio.create_task(
            process_run(run, "publication-live-flow", saver, store, PacedModel(actual))
        )
        while not task.done():
            if stopped():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise SystemExit(75)
            await asyncio.sleep(0.2)
        await task
    assert not stopped()
    with transaction() as db:
        finished = db.get(Run, run.id)
        assert finished.status in {"completed", "waiting"}, finished.error
        print(
            json.dumps(
                {
                    "run_id": run.id,
                    "status": finished.status,
                    "real_provider": True,
                    "single_attempt": True,
                    "minimum_request_spacing_seconds": 30,
                    "timeout_scope": timeout_scope,
                }
            )
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(
        level=logging.INFO,
        filename=ROOT / ".data/logs/prepublication-live.err.log",
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    logging.getLogger().addHandler(QuotaStop())
    asyncio.run(main())
