"""Current-source API/worker load in a new disposable database; no provider calls.

Run through prepublication_run.py. The parent owns every child and every row it
creates. Native user data, configuration and service processes are not touched.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import selectors
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "artifacts/prepublication/results.json"


def stopped():
    state = json.loads(LEDGER.read_text())
    return bool(state.get("halt") or state.get("external_blocker"))


def validate_sample_coverage(samples, duration):
    """Reject sleep/stalls instead of counting elapsed idle time as load."""
    times = [0.0, *(sample["elapsed_seconds"] for sample in samples), duration]
    assert samples and all(0 <= b - a <= 90 for a, b in zip(times, times[1:], strict=False)), (
        "Load measurement interrupted: missing samples or a gap over 90 seconds; "
        "keep the laptop awake and repeat the benchmark."
    )


def configure(run_id, port):
    from dotenv import dotenv_values

    assert re.fullmatch(r"[a-z0-9_]{1,35}", run_id)
    assert 8010 <= port <= 8099
    database = "nexus_perf_" + run_id
    values = dotenv_values(ROOT / ".env")
    admin = str(values["DATABASE_URL"]).replace("postgresql+psycopg://", "postgresql://")
    assert admin.rsplit("/", 1)[1] != database
    url = admin.rsplit("/", 1)[0] + "/" + database
    os.environ.update(
        DATABASE_URL=url.replace("postgresql://", "postgresql+psycopg://"),
        DATA_DIR=str(ROOT / ".data" / database),
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        AI_PROVIDER="gemini",
        FREE_ONLY="true",
        APP_ORIGIN=f"http://127.0.0.1:{port}",
        COOKIE_SECURE="false",
        PYTHONPATH=str(ROOT / "apps/api"),
    )
    sys.path.insert(0, str(ROOT / "apps/api"))
    return admin, database


async def worker(duration):
    from langchain_core.messages import AIMessageChunk
    from nexus.config import settings
    from nexus.db import transaction
    from nexus.graph_resources import resources
    from nexus.worker import claim_run, process_run
    from sqlalchemy import text

    assert not settings.gemini_api_key and not settings.openai_api_key
    with transaction() as db:
        assert (
            db.scalar(text("SELECT current_database()")) == settings.database_url.rsplit("/", 1)[1]
        )
        assert settings.database_url.rsplit("/", 1)[1].startswith("nexus_perf_")

    class ControlledModel:
        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            await asyncio.sleep(1)
            yield AIMessageChunk(
                content="Controlled load reply; real graph and persistence, no external provider."
            )

    identity = "publication-perf-" + str(os.getpid())
    deadline = time.monotonic() + duration
    async with resources() as (saver, store):
        while time.monotonic() < deadline and not stopped():
            run = claim_run(identity)
            if run:
                assert run.input.get("publication_load") is True
                await process_run(run, identity, saver, store, ControlledModel())
            else:
                await asyncio.sleep(0.2)


def telemetry(children):
    # Capture only process trees launched by this script. Windows venv Python
    # launchers can have a second Python child; include both in each role total.
    roots = ",".join(str(process.pid) for _, process in children)
    script = r"""
$all = @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId)
$roots = @(__ROOTS__)
$result = foreach ($rootId in $roots) {
  $ids = @([int]$rootId)
  do {
    $more = @($all | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | ForEach-Object { [int]$_.ProcessId })
    $ids += $more
  } while ($more.Count -gt 0)
  $rows = @(Get-Process -Id $ids -ErrorAction SilentlyContinue)
  [pscustomobject]@{
    root=[int]$rootId; process_count=$rows.Count
    private_bytes=($rows | Measure-Object PrivateMemorySize64 -Sum).Sum
    working_set_bytes=($rows | Measure-Object WorkingSet64 -Sum).Sum
    cpu_seconds=($rows | Measure-Object CPU -Sum).Sum
    handles=($rows | Measure-Object HandleCount -Sum).Sum
  }
}
ConvertTo-Json -InputObject @($result) -Compress
""".replace("__ROOTS__", roots)
    rows = json.loads(
        subprocess.check_output(["pwsh", "-NoProfile", "-Command", script], text=True, timeout=20)
    )
    for row, (role, process) in zip(rows, children, strict=True):
        assert row["root"] == process.pid and row["process_count"] >= 1
        row["role"] = role
    return rows


def run(args, admin, database):
    import httpx
    import psycopg
    from psycopg import sql

    assert os.name == "nt", "This telemetry implementation measures Windows process trees."
    assert not stopped()
    evidence = ROOT / "artifacts/prepublication" / (args.run_id + "-native-load")
    evidence.mkdir(exist_ok=False)
    with psycopg.connect(admin, autocommit=True) as db:
        assert not db.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
        ).fetchone(), "Existing benchmark database preserved; choose a new run ID."
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "nexus.migrate_graph"], cwd=ROOT, check=True)
    from nexus.config import settings
    from nexus.db import engine, transaction
    from nexus.models import Conversation, Message, Run, RunEvent, User
    from nexus.security import hasher
    from sqlalchemy import func, select, text

    assert not settings.provider_key
    children = []
    handles = []
    source_files = sorted((ROOT / "apps/api/nexus").glob("*.py"))
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    report = {
        "scope": "Current-source native API and real SQL/graph/queue/checkpoints; controlled one-second model, no external calls. Windows process-tree private memory/CPU sampled every minute. Not provider latency or a public capacity SLA.",
        "database": database,
        "duration_requested_seconds": args.duration,
        "phases": [],
        "samples": [],
        "complete": False,
        "source_sha256": source_hashes,
    }

    def save():
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n")

    def launch(role, mode):
        output = (evidence / (f"{len(handles):02d}-" + role + ".log")).open("w")
        handles.append(output)
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                mode,
                "--run-id",
                args.run_id,
                "--duration",
                str(args.duration + 600),
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        children.append((role, process))

    def stop_workers():
        for role, process in list(children):
            if role.startswith("worker"):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True
                )
                process.wait(timeout=20)
                children.remove((role, process))

    next_user = 0

    def enqueue(count):
        nonlocal next_user
        ids = []
        with transaction() as db:
            assert db.scalar(text("SELECT current_database()")) == database
            for _ in range(count):
                thread = Conversation(user_id=users[next_user % 10], title="Controlled load")
                next_user += 1
                db.add(thread)
                db.flush()
                run = Run(
                    user_id=thread.user_id,
                    conversation_id=thread.id,
                    input={"message": "Controlled load", "mode": "auto", "publication_load": True},
                )
                db.add(run)
                db.flush()
                db.add(
                    Message(
                        user_id=thread.user_id,
                        conversation_id=thread.id,
                        run_id=run.id,
                        role="user",
                        content="Controlled load",
                    )
                )
                ids.append(run.id)
        return ids

    def counts():
        with transaction() as db:
            return {
                "completed": db.scalar(
                    select(func.count()).select_from(Run).where(Run.status == "completed")
                ),
                "failed": db.scalar(
                    select(func.count()).select_from(Run).where(Run.status == "failed")
                ),
                "pending": db.scalar(
                    select(func.count())
                    .select_from(Run)
                    .where(Run.status.in_(["queued", "running", "waiting"]))
                ),
                "messages": db.scalar(select(func.count()).select_from(Message)),
                "database_bytes": db.scalar(text("SELECT pg_database_size(current_database())")),
            }

    save()
    try:
        launch("api", "api")
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}",
            headers={"Origin": f"http://127.0.0.1:{args.port}"},
            timeout=20,
        )
        ready = False
        for _ in range(90):
            assert not stopped()
            assert children[0][1].poll() is None, (
                "Temporary API exited during startup; see its isolated log"
            )
            try:
                ready = client.get("/health/ready").status_code == 200
            except httpx.ConnectError:
                pass
            if ready:
                break
            time.sleep(1)
        assert ready
        users = []
        # Seed synthetic accounts directly: testing sustained load must not
        # disable or exhaust the real eight-registrations/hour protection.
        password_hash = hasher.hash("synthetic-perf-password")
        with transaction() as db:
            assert db.scalar(text("SELECT current_database()")) == database
            for index in range(10):
                user = User(
                    name=f"Load user {index}",
                    email=f"publication-perf-{args.run_id}-{index}@example.com",
                    password_hash=password_hash,
                )
                db.add(user)
                db.flush()
                users.append(user.id)
            assert db.scalar(select(func.count()).select_from(User)) == 10
        login = client.post(
            "/auth/login",
            json={
                "email": f"publication-perf-{args.run_id}-0@example.com",
                "password": "synthetic-perf-password",
            },
        )
        assert login.status_code == 200
        # Nonstandard origins correctly receive Secure cookies. This synthetic
        # direct-loopback HTTP client explicitly carries its own test session,
        # as in the Docker load fixture; app cookie protections stay unchanged.
        session = login.cookies.get("nexus_session")
        assert session
        client.cookies.clear()
        client.cookies.set("nexus_session", session)
        assert client.get("/me").status_code == 200
        for workers in [1, 3]:
            ids = enqueue(10)
            started = time.monotonic()
            for index in range(workers):
                launch(f"worker{index}", "worker")
            while True:
                assert not stopped()
                with transaction() as db:
                    runs = list(db.scalars(select(Run).where(Run.id.in_(ids))))
                    assert not any(run.status == "failed" for run in runs)
                    if all(run.status == "completed" for run in runs):
                        assert all(run.attempts == 1 for run in runs)
                        begins = list(
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
                        # The worker commits status before its terminal event.
                        # Observe both commits instead of racing their visibility.
                        if len(begins) == len(ends) == 10:
                            break
                assert time.monotonic() - started < 180, "Controlled queue failed to drain"
                time.sleep(0.3)
            report["phases"].append(
                {
                    "workers": workers,
                    "users": 10,
                    "completed": 10,
                    "attempts_each": 1,
                    "startup_and_drain_seconds": time.monotonic() - started,
                    "processing_span_seconds": (max(ends) - min(begins)).total_seconds(),
                }
            )
            save()
            if workers == 1:
                stop_workers()
        started = time.monotonic()
        next_queue = next_sample = started
        reads = 0
        while time.monotonic() - started < args.duration:
            assert not stopped()
            assert all(process.poll() is None for _, process in children), (
                "An owned API/worker exited"
            )
            for route in ["/tasks", "/notes", "/memories", "/projects"]:
                response = client.get(route)
                assert response.status_code == 200, f"Controlled read HTTP{response.status_code}"
                reads += 1
            current = time.monotonic()
            if current >= next_queue:
                enqueue(2)
                next_queue = current + 5
            if current >= next_sample:
                measurement = counts()
                assert measurement["failed"] == 0
                processes = telemetry(children)
                if report["samples"]:
                    previous = report["samples"][-1]
                    interval = current - previous["elapsed_seconds"] - started
                    for process, prior in zip(processes, previous["processes"], strict=True):
                        assert process["role"] == prior["role"] and process["root"] == prior["root"]
                        process["cpu_percent_of_one_core"] = (
                            100 * (process["cpu_seconds"] - prior["cpu_seconds"]) / interval
                        )
                report["samples"].append(
                    {
                        "elapsed_seconds": current - started,
                        "reads": reads,
                        "growth": measurement,
                        "processes": processes,
                    }
                )
                save()
                print(
                    f"Load {current - started:.0f}s: {reads} reads, {measurement['completed']} completed, {measurement['pending']} pending",
                    flush=True,
                )
                next_sample = current + 60
            time.sleep(0.5)
        report["duration_seconds"] = time.monotonic() - started
        validate_sample_coverage(report["samples"], report["duration_seconds"])
        deadline = time.monotonic() + 60
        while counts()["pending"]:
            assert not stopped() and time.monotonic() < deadline
            time.sleep(0.3)
        report["final"] = counts()
        assert report["final"]["failed"] == 0
        report["successful_reads"] = reads
        if len(report["samples"]) >= 10:
            report["private_memory_change_bytes"] = {
                role: statistics.median(
                    next(p["private_bytes"] for p in s["processes"] if p["role"] == role)
                    for s in report["samples"][-5:]
                )
                - statistics.median(
                    next(p["private_bytes"] for p in s["processes"] if p["role"] == role)
                    for s in report["samples"][:5]
                )
                for role, _ in children
            }
            report["memory_growth_over_128mib"] = any(
                delta > 128 * 1024**2 for delta in report["private_memory_change_bytes"].values()
            )
        report["hour_completed"] = report["duration_seconds"] >= 3600
        assert source_hashes == {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "apps/api/nexus").glob("*.py"))
        }, "Application source changed during the measurement"
        report["complete"] = True
        save()
        client.close()
    finally:
        # These PIDs are only this parent's Popen children, never normal services.
        for _, process in children:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True
                )
                process.wait(timeout=20)
        for handle in handles:
            handle.close()
        engine.dispose()
        if report["complete"] and not stopped():
            with psycopg.connect(admin, autocommit=True) as db:
                db.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )
            report["disposable_database_removed"] = True
            save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "api", "worker"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration", type=int, default=3600)
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    assert args.duration >= 1
    assert not stopped()
    admin, database = configure(args.run_id, args.port)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.mode == "run":
        run(args, admin, database)
    elif args.mode == "worker":
        asyncio.run(worker(args.duration))
    else:
        import uvicorn

        server = uvicorn.Server(
            uvicorn.Config("nexus.main:app", host="127.0.0.1", port=args.port, loop="asyncio")
        )
        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )


if __name__ == "__main__":
    main()
