"""Real worker lease/recovery checks restricted to synthetic isolated browser accounts."""

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
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "apps/api"))
from langchain_core.messages import AIMessageChunk  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Run, User, now  # noqa: E402
from nexus.worker import claim_run, process_run, recover  # noqa: E402
from sqlalchemy import text  # noqa: E402

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

action, identity = sys.argv[1:3]
with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    target = db.get(User if action == "worker" else Run, identity)
    assert target
    user = target if action == "worker" else db.get(User, target.user_id)
    assert user.email.startswith("publication-history-ops-") and user.email.endswith("@example.com")

if action == "leases":
    samples = []
    started = time.monotonic()
    while time.monotonic() - started < 7:
        with transaction() as db:
            run = db.get(Run, identity)
            assert run.status == "running"
            lease = run.lease_until.isoformat()
        if not samples or samples[-1]["lease"] != lease:
            samples.append({"elapsed": round(time.monotonic() - started, 2), "lease": lease})
        if len(samples) >= 4:
            break
        time.sleep(0.2)
    assert len(samples) >= 3, "Lease did not refresh"
    print(json.dumps(samples))
elif action == "recover":
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        with transaction() as db:
            run = db.get(Run, identity)
            assert run.status == "running"
            expired = run.lease_until < now()
        if expired:
            recover()
            print("Expired real worker lease recovered; clock was not modified.")
            break
        time.sleep(0.2)
    else:
        raise TimeoutError("Killed worker lease never expired")
elif action == "sdk-hang":
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from langchain_google_genai import ChatGoogleGenerativeAI
    from nexus.config import settings
    from pydantic import SecretStr

    assert settings.request_timeout_seconds == 60

    class HangingEndpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            time.sleep(75)  # The SDK's actual 60s request deadline must fire first.
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), HangingEndpoint)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def hang():
        run = claim_run("ops-local-sdk-timeout")
        assert run and run.id == identity
        model = ChatGoogleGenerativeAI(
            model=settings.gemini_chat_model,
            api_key=SecretStr("synthetic-local-only-no-provider-access"),
            vertexai=False,
            base_url=f"http://127.0.0.1:{server.server_port}",
            request_timeout=settings.request_timeout_seconds,
            retries=2,
            include_thoughts=False,
        )
        async with resources() as (saver, store):
            await process_run(run, "ops-local-sdk-timeout", saver, store, model)

    try:
        asyncio.run(hang())
        print("Local Gemini SDK hang test completed; no external provider was contacted.")
    finally:
        server.shutdown()
        server.server_close()
elif action == "worker":

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            await asyncio.sleep(1)
            yield AIMessageChunk(content="One worker processed this queued job exactly once.")

    async def work():
        async with resources() as (saver, store):
            while run := claim_run("ops-worker-" + str(os.getpid())):
                assert run.user_id == identity
                await process_run(run, run.worker_id, saver, store, Provider())

    asyncio.run(work())
else:
    raise ValueError("Unknown isolated operation")
