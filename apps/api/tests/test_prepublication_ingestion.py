"""Controlled ingestion faults; simulated HTTP 429 is loopback only, not real quota."""

import asyncio
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import ROOT, register
from nexus import provider
from nexus.config import settings
from nexus.db import transaction
from nexus.models import Chunk, Document, IngestionJob, now
from nexus.worker import ingestion_loop, recover
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_simulated_embedding_429_retries_three_times_then_fails_job(client, monkeypatch):
    register(client)
    doc = client.post(
        "/documents",
        files={
            "file": (
                "simulated-rate-limit.txt",
                b"Cedar Lantern controlled rate-limit evidence.",
                "text/plain",
            )
        },
    ).json()
    requests = []

    class LimitedEndpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(self.path)
            payload = json.dumps(
                {
                    "error": {
                        "code": 429,
                        "message": "SIMULATED local rate limit",
                        "status": "RESOURCE_EXHAUSTED",
                    }
                }
            ).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), LimitedEndpoint)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = provider.genai.Client
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "synthetic-loopback-only-not-a-provider-key")
    monkeypatch.setattr(settings, "free_only", True)

    def loopback_client(*, api_key, vertexai, http_options):
        assert api_key == "synthetic-loopback-only-not-a-provider-key" and vertexai is False
        assert http_options.retry_options.attempts == 3
        return original(
            api_key=api_key,
            vertexai=False,
            http_options=http_options.model_copy(
                update={"base_url": f"http://127.0.0.1:{server.server_port}"}
            ),
        )

    monkeypatch.setattr(provider.genai, "Client", loopback_client)
    task = asyncio.create_task(ingestion_loop("simulated-limit-worker"))
    try:
        async with asyncio.timeout(30):
            while True:
                with transaction() as db:
                    saved = db.get(Document, doc["id"])
                    status, error = saved.status, saved.error
                if status == "failed":
                    break
                assert not task.done(), "Ingestion loop unexpectedly exited"
                await asyncio.sleep(0.05)
        assert len(requests) == 3
        assert "HTTP 429" in error
        with transaction() as db:
            job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc["id"]))
            assert job.status == "failed" and job.attempts == 1
            assert db.scalar(select(func.count()).select_from(Chunk)) == 0
        (ROOT / "artifacts/prepublication/IDX-09-simulated.json").write_text(
            json.dumps(
                {
                    "simulated_http_status": 429,
                    "loopback_request_attempts": len(requests),
                    "job_status": status,
                    "chunks": 0,
                    "external_provider_contacted": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("attempts,expected", [(1, "queued"), (2, "queued"), (3, "failed")])
def test_ingestion_expired_lease_has_bounded_recovery(client, attempts, expected):
    register(client)
    doc = client.post(
        "/documents",
        files={
            "file": ("lease-recovery.txt", b"Controlled expired ingestion lease.", "text/plain")
        },
    ).json()
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc["id"]))
        job.status, job.attempts, job.lease_until = (
            "processing",
            attempts,
            now() - timedelta(seconds=1),
        )
        db.get(Document, doc["id"]).status = "processing"
    recover()
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc["id"]))
        saved = db.get(Document, doc["id"])
        assert job.status == expected and saved.status == expected
        if expected == "failed":
            assert "retry indexing" in saved.error.lower()
