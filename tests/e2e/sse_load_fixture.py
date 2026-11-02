"""Fifty real authenticated proxy/API SSE sockets; no model or external requests."""

import asyncio
import json
import sys
import time

import graph_fixture  # noqa: F401 -- isolated database, blank provider keys
import httpx
from nexus.db import transaction
from nexus.events import emit
from nexus.models import Conversation, Run, User
from sqlalchemy import text


async def main():
    identity = sys.argv[1]
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, identity)
        assert (
            user
            and user.email.startswith("publication-presentation-")
            and user.email.endswith("@example.com")
        )
        thread = Conversation(user_id=identity, title="Fifty SSE connection probe")
        db.add(thread)
        db.flush()
        run = Run(
            user_id=identity, conversation_id=thread.id, input={"message": "SSE socket probe"}
        )
        db.add(run)
        db.flush()
    emit(run.id, "run.queued", {"scope": "Synthetic local SSE load"})
    ready = asyncio.Event()
    release = asyncio.Event()
    active = peak = 0
    results = []
    limits = httpx.Limits(max_connections=60, max_keepalive_connections=60)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:3001",
        headers={"Origin": "http://127.0.0.1:3001"},
        limits=limits,
        timeout=30,
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "synthetic-presentation-password"},
        )
        assert login.status_code == 200

        async def connection():
            nonlocal active, peak
            async with client.stream("GET", f"/api/runs/{run.id}/events") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]
                lines = response.aiter_lines()
                async for line in lines:
                    if line.startswith("data:"):
                        event = json.loads(line[5:])
                        assert event["run_id"] == run.id and event["type"] == "run.queued"
                        break
                active += 1
                peak = max(peak, active)
                if active == 50:
                    ready.set()
                try:
                    assert not response.is_closed
                    await release.wait()
                finally:
                    active -= 1
                    await lines.aclose()

        jobs = [asyncio.create_task(connection()) for _ in range(50)]
        try:
            await asyncio.wait_for(ready.wait(), 45)
            assert peak == 50
            for _ in range(5):
                started = time.monotonic()
                health = await client.get("/api/health/ready")
                assert health.status_code == 200 and health.json()["database"] is True
                results.append(round(time.monotonic() - started, 3))
                await asyncio.sleep(1)
        finally:
            release.set()
            await asyncio.gather(*jobs)
        removed = await client.delete(f"/api/conversations/{thread.id}?version=1")
        assert removed.status_code == 200
    print(
        json.dumps(
            {
                "simultaneous_sse_connections": peak,
                "each_received_authorized_event": True,
                "health_seconds_while_held": results,
                "synthetic_conversation_deleted": True,
                "scope": "50actualHTTP sockets through Next proxy and API; not browser per-origin connection emulation, no model calls.",
            }
        )
    )


asyncio.run(main())
