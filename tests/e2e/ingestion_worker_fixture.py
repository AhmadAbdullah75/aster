"""Actual ingestion loop and natural lease recovery, isolated synthetic document only."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(ROOT / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
os.environ["DATA_DIR"] = str(ROOT / ".data/e2e")
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus import documents  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.models import Document, IngestionJob, User, now  # noqa: E402
from nexus.worker import ingestion_loop, recover  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

mode, document_id = sys.argv[1:3]
with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    doc = db.get(Document, document_id)
    assert doc
    user = db.get(User, doc.user_id)
    assert user.email.startswith("publication-upload-") and user.email.endswith("@example.com")


def state():
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == document_id))
        doc = db.get(Document, document_id)
        return {
            "document_status": doc.status,
            "job_status": job.status,
            "attempts": job.attempts,
            "error": doc.error,
        }


if mode == "recover":
    deadline = time.monotonic() + 260
    while time.monotonic() < deadline:
        with transaction() as db:
            job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == document_id))
            assert job.status == "processing"
            expired = job.lease_until < now()
        if expired:
            recover()
            break
        time.sleep(0.2)
    else:
        raise TimeoutError("Actual ingestion lease did not expire")
    print(json.dumps(state()))
elif mode == "status":
    print(json.dumps(state()))
else:
    assert mode in {"slow", "fast"}
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def embed(texts):
        if mode == "slow":
            (ROOT / f"artifacts/prepublication/ingestion-active-{document_id}.json").write_text(
                '{"embedding_started": true}', encoding="utf-8"
            )
            await asyncio.sleep(400)
        return [[0.1] * 1536 for _ in texts]

    documents.embed = embed

    async def main():
        task = asyncio.create_task(ingestion_loop("isolated-ingestion-" + str(os.getpid())))
        try:
            while state()["document_status"] != "ready":
                assert not task.done(), "Ingestion loop exited unexpectedly"
                await asyncio.sleep(0.2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(main())
