import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

import pytest
from conftest import ROOT, register
from nexus import documents, provider
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Chunk, Document, IngestionJob, Message, Run, now
from nexus.worker import claim_run, process_run, recover
from sqlalchemy import func, select
from test_graph import FakeModel, setup_run


async def fake_embedding(texts):
    return [[1.0, 0.0] + [0.0] * 1534 for _ in texts]


@pytest.mark.asyncio
async def test_ingestion_retry_hybrid_coverage_isolation_and_deleted_sources(client, monkeypatch):
    user = register(client)
    project = client.post("/projects", json={"title": "Launch"}).json()
    monkeypatch.setattr(documents, "embed", fake_embedding)
    content = b"# Discovery\nConfirm scope.\n# Build\nImplement portal.\n# Launch\nReview delivery milestone."
    upload = client.post(
        "/documents",
        files={"file": ("proposal.md", content, "text/markdown")},
        data={"project_id": project["id"]},
    ).json()
    again = client.post(
        "/documents",
        files={"file": ("proposal.md", content, "text/markdown")},
        data={"project_id": project["id"]},
    ).json()
    assert again["id"] == upload["id"]
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == upload["id"]))
        job.worker_id, job.status = "ingestion-test", "processing"
    await documents.ingest(upload["id"], "ingestion-test")
    retrieval_started = time.perf_counter()
    result = await documents.search(user["id"], "delivery milestone", project["id"], [upload["id"]])
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts/retrieval-timing.json").write_text(
        json.dumps(
            {
                "retrieval_ms": round((time.perf_counter() - retrieval_started) * 1000, 2),
                "chunks": 3,
                "provider_latency": "excluded; deterministic embedding fixture",
                "database": "actual PostgreSQL/pgvector + FTS",
            },
            indent=2,
        )
    )
    assert result["sources"] and any(
        "delivery milestone" in s["excerpt"] for s in result["sources"]
    )
    full = await documents.search(
        user["id"], "summarize whole proposal", project["id"], [upload["id"]], coverage=True
    )
    assert full["complete"] and full["covered_chunks"] == 3
    assert {"Section 1", "Section 2", "Section 3"} == {s["section"] for s in full["sources"]}
    assert not (await documents.search("different-user", "delivery", None, []))["sources"]
    source_id = result["sources"][0]["id"]
    assert client.get("/sources/" + source_id).status_code == 200
    assert client.post("/documents/" + upload["id"] + "/retry").status_code == 200
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == upload["id"]))
        job.worker_id, job.status = "ingestion-test", "processing"
    await documents.ingest(upload["id"], "ingestion-test")
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 3
    assert client.delete("/documents/" + upload["id"] + "?version=1").status_code == 200
    assert client.get("/sources/" + source_id).status_code == 404
    await documents.ingest(upload["id"], "ingestion-test")
    assert not (await documents.search(user["id"], "delivery", project["id"], []))["sources"]


@pytest.mark.asyncio
async def test_cancellation_partial_output_and_worker_recovery(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)

    class SlowModel(FakeModel):
        async def astream(self, messages):
            from langchain_core.messages import AIMessageChunk

            yield AIMessageChunk(content="Partial output " * 10)
            await asyncio.sleep(30)

    async with resources() as (saver, store):
        task = asyncio.create_task(process_run(run, "test-worker", saver, store, SlowModel([])))
        for _ in range(100):
            with transaction() as db:
                partial = db.scalar(
                    select(Message).where(Message.run_id == run.id, Message.role == "assistant")
                )
            if partial:
                break
            await asyncio.sleep(0.05)
        assert partial
        assert client.post("/runs/" + run.id + "/cancel").status_code == 200
        await asyncio.wait_for(task, timeout=5)
    history = client.get("/conversations/" + thread["id"] + "/history").json()
    assert history["messages"][-1]["interrupted"] and history["runs"][0]["status"] == "canceled"
    response = client.post("/conversations/" + thread["id"] + "/runs", json={"message": "retry"})
    assert response.status_code == 202
    stranded = claim_run("crashed-worker")
    with transaction() as db:
        db.get(Run, stranded.id).lease_until = now() - timedelta(seconds=1)
    recover()
    assert client.get("/runs/" + stranded.id).json()["status"] == "failed"


@pytest.mark.asyncio
async def test_forced_modes_and_provider_outage_honesty(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    with transaction() as db:
        db.get(Run, run.id).input = {**run.input, "mode": "web"}
        run.input = {**run.input, "mode": "web"}

    async def outage(query):
        raise TimeoutError("synthetic provider outage")

    monkeypatch.setattr(provider, "web_search", outage)
    model = FakeModel([{"content": "Web search failed; I cannot confirm fresh information."}])
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    tool_messages = [m for m in model.prompts[0] if m.type == "tool"]
    assert tool_messages and "error" in tool_messages[0].content
    events = client.get("/runs/" + run.id + "/events").text
    assert "web_search" in events and "source.added" not in events


@pytest.mark.asyncio
async def test_project_delete_cascades_graph_jobs_and_prevents_resurrection(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    project = client.post("/projects", json={"title": "Disposable"}).json()
    response = client.put(
        "/conversations/" + thread["id"],
        json={"title": "In project", "project_id": project["id"], "version": 2},
    )
    assert response.status_code == 200, response.text
    doc = client.post(
        "/documents",
        data={"project_id": project["id"]},
        files={"file": ("pending.txt", b"queued data", "text/plain")},
    ).json()
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, FakeModel([{"content": "Completed."}]))
    assert client.delete("/projects/" + project["id"] + "?version=1").status_code == 200
    assert client.get("/conversations/" + thread["id"]).status_code == 404
    assert client.get("/runs/" + run.id).status_code == 404
    async with resources() as (saver, store):
        assert not (await saver.aget_tuple({"configurable": {"thread_id": thread["id"]}}))
    await documents.ingest(doc["id"], "deleted-worker")
    with transaction() as db:
        assert not db.get(Document, doc["id"])
        assert not list(db.scalars(select(IngestionJob)))


@pytest.mark.asyncio
async def test_hard_worker_process_crash_recovers_partial_run(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    with transaction() as db:
        db.get(Run, run.id).status = "queued"
    child = subprocess.Popen(
        [sys.executable, str(ROOT / "apps/api/tests/worker_child.py")],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        partial = None
        # Windows cold imports can exceed ten seconds while Next is building.
        # Still fail immediately if the worker exits, rather than hiding a crash.
        deadline = asyncio.get_running_loop().time() + 45
        while asyncio.get_running_loop().time() < deadline:
            assert child.poll() is None, "Worker exited before persisting a partial response"
            with transaction() as db:
                partial = db.scalar(
                    select(Message).where(Message.run_id == run.id, Message.role == "assistant")
                )
            if partial:
                break
            await asyncio.sleep(0.05)
        assert partial and partial.content
        child.kill()
        child.wait(timeout=10)
        with transaction() as db:
            db.get(Run, run.id).lease_until = now() - timedelta(seconds=1)
        recover()
        saved = client.get("/conversations/" + thread["id"] + "/history").json()
        assert saved["runs"][0]["status"] == "failed"
        assert saved["messages"][-1]["interrupted"]
        assert saved["messages"][-1]["content"] == partial.content
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@pytest.mark.asyncio
async def test_claimed_run_cannot_recreate_deleted_checkpoints(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    assert client.delete("/conversations/" + thread["id"] + "?version=2").status_code == 200
    async with resources() as (saver, store):
        await process_run(
            run, "test-worker", saver, store, FakeModel([{"content": "Must never execute"}])
        )
        assert await saver.aget_tuple({"configurable": {"thread_id": thread["id"]}}) is None
    assert client.get("/runs/" + run.id).status_code == 404


def test_deletion_marker_fences_new_project_work(client, monkeypatch):
    register(client)
    project = client.post("/projects", json={"title": "Deleting project"}).json()
    from nexus.models import Project

    with transaction() as db:
        db.get(Project, project["id"]).deleting = True
    assert client.post("/conversations", json={"project_id": project["id"]}).status_code == 404
    assert (
        client.post("/tasks", json={"title": "Blocked", "project_id": project["id"]}).status_code
        == 404
    )
    # Repeating delete safely finishes cleanup after a prior API interruption.
    assert client.delete("/projects/" + project["id"] + "?version=1").status_code == 200
