"""Bounded real-provider smoke suite; no test-provider substitution. Uses a disposable DB."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / ".env")
key_name = "GEMINI_API_KEY" if values.get("AI_PROVIDER", "gemini") == "gemini" else "OPENAI_API_KEY"
if not values.get(key_name):
    print(
        f"BLOCKED: Add {key_name} directly to the root .env, then rerun this command. Never paste the key into chat."
    )
    raise SystemExit(2)
base_url = str(values["DATABASE_URL"]).replace("postgresql+psycopg://", "postgresql://")
test_url = base_url.rsplit("/", 1)[0] + "/nexus_live_smoke"
os.environ["DATABASE_URL"] = test_url.replace("postgresql://", "postgresql+psycopg://")
os.environ["DATA_DIR"] = str(root / ".data" / "live-smoke")
os.environ["MAX_TOOL_CALLS"] = "5"
os.environ["MAX_OUTPUT_TOKENS"] = "2048"
os.environ["PYTHONPATH"] = str(root / "apps" / "api")
sys.path.insert(0, os.environ["PYTHONPATH"])
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
with psycopg.connect(base_url, autocommit=True) as admin:
    if admin.execute("SELECT 1 FROM pg_database WHERE datname='nexus_live_smoke'").fetchone():
        print(
            "A previous nexus_live_smoke database exists. Inspect it and remove it explicitly before rerunning."
        )
        raise SystemExit(2)
    admin.execute("CREATE DATABASE nexus_live_smoke")
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True)
subprocess.run([sys.executable, "-m", "nexus.migrate_graph"], cwd=root, check=True)

from nexus.actions import decide  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import engine, transaction  # noqa: E402
from nexus.documents import ingest, search  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import (  # noqa: E402
    Conversation,
    Document,
    IngestionJob,
    Message,
    Proposal,
    Run,
    Task,
    User,
    uid,
)  # noqa: E402
from nexus.provider import web_search  # noqa: E402
from nexus.schemas import Decision  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402
from sqlalchemy import select  # noqa: E402

results = {}


def queue(user_id, thread_id, message):
    with transaction() as db:
        run = Run(user_id=user_id, conversation_id=thread_id, input={"message": message})
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user_id,
                conversation_id=thread_id,
                run_id=run.id,
                role="user",
                content=message,
            )
        )
    return claim_run("live-smoke")


async def main():
    settings.blobs.mkdir(parents=True, exist_ok=True)
    with transaction() as db:
        user = User(
            email="smoke@example.com",
            name="Synthetic Smoke",
            password_hash="no-login-smoke-account",
        )
        db.add(user)
        db.flush()
        conversation = Conversation(user_id=user.id, title="Live provider smoke")
        db.add(conversation)
        db.flush()
        user_id, thread_id = user.id, conversation.id
    async with resources() as (saver, store):
        run = queue(
            user_id,
            thread_id,
            "Use the calculator tool to compute 137 * 9, then briefly explain the result. Do not use other tools.",
        )
        await process_run(run, "live-smoke", saver, store)
        with transaction() as db:
            assert db.get(Run, run.id).status == "completed", db.get(Run, run.id).error
        snapshot = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        assert snapshot and any(
            getattr(m, "name", "") == "calculator" or getattr(m, "tool_calls", [])
            for m in snapshot.checkpoint["channel_values"]["messages"]
        ), "Provider did not call a tool."
        results["chat_and_tool_calling"] = "passed"
        blob = uid() + ".md"
        (settings.blobs / blob).write_text(
            (root / "docs/example-proposal.md").read_text(), encoding="utf-8"
        )
        with transaction() as db:
            doc = Document(
                user_id=user_id,
                filename="Synthetic proposal.md",
                blob=blob,
                sha256=uid(),
                size=800,
                media_type="text/markdown",
            )
            db.add(doc)
            db.flush()
            db.add(IngestionJob(document_id=doc.id, status="processing", worker_id="live-smoke"))
            doc_id = doc.id
        await ingest(doc_id, "live-smoke")
        evidence = await search(
            user_id, "What is the eighth project day milestone?", None, [doc_id]
        )
        assert evidence["sources"] and any("eighth" in s["excerpt"] for s in evidence["sources"])
        results["embeddings_and_retrieval"] = "passed"
        fresh = await web_search(
            "Find the official NASA page explaining why Mars looks red. Cite its URL. One search is enough."
        )
        assert fresh["sources"] and all(
            s.get("url", "").startswith("http") for s in fresh["sources"]
        )
        results["web_search_real_annotations"] = "passed"
        run = queue(
            user_id,
            thread_id,
            "Use propose_action with tasks.create to propose exactly one task titled Synthetic smoke task. No due date or project. Do not use other tools. Wait for my approval.",
        )
        await process_run(run, "live-smoke", saver, store)
        with transaction() as db:
            assert db.get(Run, run.id).status == "waiting"
            assert not list(db.scalars(select(Task)))
            proposal = db.scalar(
                select(Proposal).where(Proposal.run_id == run.id, Proposal.status == "pending")
            )
            assert proposal
            proposal_id = proposal.id
        decide(user_id, proposal_id, Decision(approve=True, version=1))
        await process_run(claim_run("live-smoke"), "live-smoke", saver, store)
        with transaction() as db:
            assert db.get(Run, run.id).status == "completed"
            assert len(list(db.scalars(select(Task)))) == 1
        results["hitl_continuation"] = "passed"
    print(
        "Live smoke passed: chat/tools, embeddings/retrieval, web search annotations, approval continuation."
    )


try:
    asyncio.run(main())
finally:
    (root / "artifacts").mkdir(exist_ok=True)
    (root / "artifacts/live-smoke.json").write_text(json.dumps(results, indent=2))
    engine.dispose()
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE nexus_live_smoke WITH (FORCE)")
