"""A large number of short sections must fit the real graph's evidence budget."""

import json

import pytest
from conftest import register
from langchain_core.messages import AIMessageChunk
from nexus import documents
from nexus.config import settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import IngestionJob
from nexus.worker import claim_run, process_run
from sqlalchemy import select


@pytest.mark.asyncio
async def test_81_section_summary_reports_partial_without_context_overflow(client, monkeypatch):
    register(client)
    content = "\n".join(
        f"# Coverage section {number:03d}\nThe verification label for milestone{number:03d} is COVERAGE{number:03d}.\n"
        for number in range(81)
    ).encode()
    doc = client.post(
        "/documents", files={"file": ("coverage-81.md", content, "text/markdown")}
    ).json()

    async def embed(texts):
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(documents, "embed", embed)
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc["id"]))
        job.status, job.worker_id = "processing", "coverage-worker"
    await documents.ingest(doc["id"], "coverage-worker")
    thread = client.post("/conversations", json={}).json()
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-not-a-provider-key")
    accepted = client.post(
        f"/conversations/{thread['id']}/runs",
        json={
            "message": "Summarize the entire document and disclose exact coverage.",
            "mode": "documents",
            "document_ids": [doc["id"]],
        },
    )
    assert accepted.status_code == 202

    class CoverageProvider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            data = json.loads(messages[-1].content)
            assert data["coverage"] is True and data["total_chunks"] == 81
            assert data["complete"] is False
            assert 0 < data["covered_chunks"] <= 80
            yield AIMessageChunk(
                content=f"Coverage is partial: {data['covered_chunks']} of {data['total_chunks']} chunks."
            )

    async with resources() as (saver, store):
        await process_run(
            claim_run("coverage-worker"), "coverage-worker", saver, store, CoverageProvider()
        )
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][0]["status"] == "completed", history["runs"][0]["error"]
    assert "Coverage is partial" in history["messages"][-1]["content"]
