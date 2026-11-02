"""Bounded, light read-only stability traffic against the native synthetic account.

Does not invoke chat, tools, document indexing, or any external provider. Run via
prepublication_run.py so quota/storage stops terminate the owned process tree.
"""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "artifacts/prepublication/results.json"
EMAIL = "nexus-smoke-publication-20261024a@example.com"
USER_ID = "15c1d056-30cd-4772-be15-713e487df802"


def stopped():
    state = json.loads(LEDGER.read_text(encoding="utf-8"))
    return bool(state.get("halt") or state.get("external_blocker"))


def process_samples():
    # Only memory/handle metadata for this application's listeners; no command
    # lines, environment, credentials or response content are written to reports.
    command = """
    $samples=@()
    foreach($port in @(3000,8000)) {
      $listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1
      $owned=Get-Process -Id $listener.OwningProcess -ErrorAction Stop
      $samples+=@{port=$port;pid=$owned.Id;working_set_bytes=$owned.WorkingSet64;private_bytes=$owned.PrivateMemorySize64;handles=$owned.HandleCount}
    }
    ConvertTo-Json -InputObject $samples -Compress
    """
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--output", default="read-soak.json")
    args = parser.parse_args()
    assert args.seconds >= 10 and args.interval >= 5
    target = (ROOT / "artifacts/prepublication" / args.output).resolve()
    assert target.is_relative_to((ROOT / "artifacts/prepublication").resolve())
    assert not stopped()
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "requested_seconds": args.seconds,
        "interval_seconds": args.interval,
        "scope": "Native synthetic account; sequential health/profile/resource GETs and listener memory/handle samples. No AI/indexing/provider calls; not an hour of conversation generation.",
        "samples": [],
        "requests": 0,
        "errors": [],
        "hour_completed": False,
    }

    def persist():
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    with httpx.Client(
        base_url="http://127.0.0.1:8000", timeout=10, headers={"Origin": "http://127.0.0.1:3000"}
    ) as client:
        login = client.post(
            "/auth/login", json={"email": EMAIL, "password": "synthetic-publication-password"}
        )
        assert login.status_code == 200, "Synthetic soak account login failed"
        assert login.json()["id"] == USER_ID
        started = time.monotonic()
        try:
            while True:
                assert not stopped(), "Testing stopped by quota/storage guard"
                sample = {"elapsed_seconds": round(time.monotonic() - started, 3), "responses": []}
                for endpoint in (
                    "/health/live",
                    "/health/ready",
                    "/me",
                    "/projects",
                    "/tasks",
                    "/notes",
                    "/documents",
                    "/memories",
                    "/conversations?limit=200",
                ):
                    assert not stopped(), "Testing stopped by quota/storage guard"
                    request_started = time.monotonic()
                    response = client.get(endpoint)
                    report["requests"] += 1
                    assert response.status_code == 200, (
                        f"Read failed: {endpoint} HTTP{response.status_code}"
                    )
                    data = response.json()
                    if endpoint == "/me":
                        assert data["id"] == USER_ID
                    sample["responses"].append(
                        {
                            "endpoint": endpoint,
                            "status": response.status_code,
                            "seconds": round(time.monotonic() - request_started, 4),
                            "response_bytes": len(response.content),
                        }
                    )
                sample["processes"] = process_samples()
                report["samples"].append(sample)
                report["elapsed_seconds"] = round(time.monotonic() - started, 3)
                persist()
                if time.monotonic() - started >= args.seconds:
                    break
                deadline = min(started + args.seconds, time.monotonic() + args.interval)
                while time.monotonic() < deadline:
                    assert not stopped(), "Testing stopped by quota/storage guard"
                    time.sleep(min(0.2, deadline - time.monotonic()))
            report["hour_completed"] = report["elapsed_seconds"] >= 3600
            report["completed_at"] = datetime.now(UTC).isoformat()
            persist()
            print(
                json.dumps(
                    {
                        key: report[key]
                        for key in ("elapsed_seconds", "requests", "hour_completed", "errors")
                    }
                )
            )
        except Exception as exc:
            report["errors"].append(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "type": type(exc).__name__,
                    "reason": "Stop flag active"
                    if stopped()
                    else "Read/process probe failed; inspect safe runner log",
                }
            )
            persist()
            raise


if __name__ == "__main__":
    main()
