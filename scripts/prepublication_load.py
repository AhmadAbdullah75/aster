"""Controlled queue/one-hour read-load measurements, isolated Docker data and dummy model only."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path.cwd()
TARGET = ROOT / ".data/prepublication-docker"
mode = sys.argv[1]
if mode == "run":
    values = dotenv_values(TARGET / "test.env")
    assert values["POSTGRES_DB"] == "nexus_publication"
    os.environ["DATABASE_URL"] = (
        f"postgresql+psycopg://{values['POSTGRES_USER']}:{values['POSTGRES_PASSWORD']}@127.0.0.1:5435/nexus_publication"
    )
    os.environ["DATA_DIR"] = str(TARGET / "unused-load-blobs")
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(ROOT / "apps/api"))

from langchain_core.messages import AIMessageChunk  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Conversation, Message, Run, RunEvent, User  # noqa: E402
from nexus.worker import claim_run, process_run  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_publication"
assert not settings.gemini_api_key and not settings.openai_api_key


def halted():
    path = (
        ROOT / "artifacts/prepublication/results.json"
        if mode == "run"
        else Path("/tmp/publication-ledger/results.json")
    )
    state = json.loads(path.read_text())
    return bool(state.get("halt") or state.get("external_blocker"))


async def worker():
    deadline = time.monotonic() + int(sys.argv[2])

    class Provider:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            await asyncio.sleep(1)
            yield AIMessageChunk(
                content="Controlled load response persisted through the real graph, SQL projections, events and checkpoints. No external provider was contacted."
            )

    identity = "publication-load-" + str(os.getpid())
    async with resources() as (saver, store):
        while time.monotonic() < deadline and not halted():
            run = claim_run(identity)
            if not run:
                await asyncio.sleep(0.2)
                continue
            assert run.input.get("publication_load") is True
            await process_run(run, identity, saver, store, Provider())


def docker(args):
    result = subprocess.run(
        ["docker", *args], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])
    return result.stdout.strip()


def enqueue(users, phase, count):
    ids = []
    with transaction() as db:
        for index in range(count):
            user = users[index % len(users)]
            thread = Conversation(
                user_id=user, title=f"Publication load {phase} {time.time_ns()}-{index}"
            )
            db.add(thread)
            db.flush()
            run = Run(
                user_id=user,
                conversation_id=thread.id,
                input={
                    "message": "Controlled queue load check",
                    "mode": "auto",
                    "publication_load": True,
                    "load_phase": phase,
                },
            )
            db.add(run)
            db.flush()
            db.add(
                Message(
                    user_id=user,
                    conversation_id=thread.id,
                    run_id=run.id,
                    role="user",
                    content=run.input["message"],
                )
            )
            ids.append(run.id)
    return ids


def growth(users):
    with transaction() as db:
        return {
            "completed_runs": db.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.user_id.in_(users), Run.status == "completed")
            ),
            "messages": db.scalar(
                select(func.count()).select_from(Message).where(Message.user_id.in_(users))
            ),
            "events": db.scalar(
                select(func.count()).select_from(RunEvent).join(Run).where(Run.user_id.in_(users))
            ),
            "table_bytes": {
                name: db.scalar(text("SELECT pg_total_relation_size(:table)"), {"table": name})
                for name in (
                    "messages",
                    "run_events",
                    "checkpoints",
                    "checkpoint_blobs",
                    "checkpoint_writes",
                )
            },
        }


def run():
    import httpx

    assert not halted()
    base = [
        "compose",
        "-p",
        "nexus-publication",
        "--env-file",
        str(TARGET / "test.env"),
        "-f",
        str(TARGET / "compose.json"),
    ]
    docker([*base, "stop", "worker"])
    source = json.loads((TARGET / "compose.json").read_text())["services"]["worker"]
    source.pop("build", None)
    source.pop("depends_on", None)
    source["image"] = "nexus-publication-worker"
    source["restart"] = "no"
    source["command"] = ["uv", "run", "python", "/tmp/load_probe.py", "worker", "3900"]
    source["volumes"] = [
        {
            "type": "bind",
            "source": str(ROOT / "scripts/prepublication_load.py"),
            "target": "/tmp/load_probe.py",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(ROOT / "artifacts/prepublication"),
            "target": "/tmp/publication-ledger",
            "read_only": True,
        },
    ]
    config = TARGET / "load.json"
    config.write_text(
        json.dumps(
            {
                "services": {"worker": source},
                "networks": {"default": {"external": True, "name": "nexus-publication_default"}},
            },
            indent=2,
        )
    )
    load = [
        "compose",
        "-p",
        "nexus-publication-load",
        "--env-file",
        str(TARGET / "test.env"),
        "-f",
        str(config),
    ]
    with transaction() as db:
        assert not db.scalar(select(Run).where(Run.status.in_(["queued", "running", "waiting"])))
        users = []
        for number in range(10):
            user = User(
                email=f"publication-load-{time.time_ns()}-{number}@example.com",
                password_hash="unused-synthetic-hash",
                name=f"Publication load {number}",
            )
            db.add(user)
            db.flush()
            users.append(user.id)
    report = {
        "scope": "Deterministic model latency1s; real queue/SQL/graph/checkpoints. No live provider calls or paid resources.",
        "baseline": growth(users),
        "phases": [],
        "samples": [],
    }
    evidence = ROOT / "artifacts/prepublication/load-verified.json"

    def save():
        evidence.write_text(json.dumps(report, indent=2) + "\n")

    try:
        for workers in [1, 3]:
            if halted():
                return
            ids = enqueue(users, f"workers-{workers}", 10)
            docker([*load, "up", "-d", "--scale", f"worker={workers}"])
            deadline = time.monotonic() + 120
            while True:
                if halted():
                    return
                with transaction() as db:
                    rows = list(db.scalars(select(Run).where(Run.id.in_(ids))))
                    if all(row.status == "completed" for row in rows):
                        starts = list(
                            db.scalars(
                                select(RunEvent.created_at).where(
                                    RunEvent.run_id.in_(ids), RunEvent.type == "run.started"
                                )
                            )
                        )
                        ends = list(
                            db.scalars(
                                select(RunEvent.created_at).where(
                                    RunEvent.run_id.in_(ids), RunEvent.type == "run.completed"
                                )
                            )
                        )
                        assert len(starts) == len(ends) == 10
                        assert all(row.attempts == 1 for row in rows)
                        report["phases"].append(
                            {
                                "workers": workers,
                                "users": 10,
                                "completed": 10,
                                "attempts_each": 1,
                                "processing_span_seconds": (
                                    max(ends) - min(starts)
                                ).total_seconds(),
                            }
                        )
                        break
                    assert not any(row.status == "failed" for row in rows)
                assert time.monotonic() < deadline, "Load phase did not drain"
                time.sleep(0.5)
            docker([*load, "stop", "worker"])
            save()
        assert (
            report["phases"][1]["processing_span_seconds"]
            < report["phases"][0]["processing_span_seconds"]
        )
        docker([*load, "up", "-d", "--scale", "worker=3"])
        client = httpx.Client(
            base_url="http://localhost:3002",
            headers={"Origin": "http://localhost:3002"},
            timeout=20,
        )
        login = client.post(
            "/api/auth/login",
            json={
                "email": "publication-docker-20261025@example.com",
                "password": "synthetic-docker-password",
            },
        )
        assert login.status_code == 200
        client.cookies.set("nexus_session", login.cookies.get("nexus_session"))
        assert client.get("/api/me").status_code == 200
        duration = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
        started = time.monotonic()
        next_queue = next_sample = started
        requests = 0
        while time.monotonic() - started < duration:
            if halted():
                return
            for route in ["/api/tasks", "/api/notes", "/api/memories", "/api/projects"]:
                response = client.get(route)
                assert response.status_code == 200, (
                    f"Controlled read {route} returned HTTP{response.status_code}"
                )
                requests += 1
            current = time.monotonic()
            if current >= next_queue:
                enqueue(users, "soak", 2)
                next_queue = current + 5
            if current >= next_sample:
                names = docker(
                    [
                        "ps",
                        "--filter",
                        "name=nexus-publication-load-worker",
                        "--format",
                        "{{.Names}} ",
                    ]
                ).split()
                stats = docker(
                    [
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{json .}}",
                        "nexus-publication-api-1",
                        *names,
                    ]
                )
                measurement = growth(users)
                report["samples"].append(
                    {
                        "elapsed_seconds": round(current - started, 2),
                        "requests": requests,
                        "growth": measurement,
                        "containers": [json.loads(line) for line in stats.splitlines()],
                    }
                )
                if measurement["completed_runs"] >= 100 and "first_100_chats" not in report:
                    report["first_100_chats"] = measurement
                if measurement["messages"] >= 1000 and "first_1000_messages" not in report:
                    report["first_1000_messages"] = measurement
                next_sample = current + 60
                save()
                print(
                    f"Load sample {current - started:.0f}s: {requests} reads, {measurement['completed_runs']} completed runs",
                    flush=True,
                )
            time.sleep(0.5)
        report["duration_seconds"] = round(time.monotonic() - started, 2)
        report["successful_reads"] = requests
        report["final"] = growth(users)
        report["complete"] = True
        save()
        client.close()
    finally:
        if not halted():
            docker([*load, "down"])
            docker([*base, "up", "-d", "worker"])


if mode == "worker":
    asyncio.run(worker())
elif mode == "run":
    run()
else:
    raise ValueError("Unknown load command")
