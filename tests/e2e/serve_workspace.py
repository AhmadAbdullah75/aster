"""Restartable real isolated API/production web pair for process-fault browser checks."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".data/e2e/workspace-control.json"
COMMAND = ROOT / ".data/e2e/workspace-command.json"
LEDGER = ROOT / "artifacts/prepublication/results.json"


def ready(url):
    try:
        with urlopen(url, timeout=1) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def stop(child):
    if child and child.poll() is None:
        # Only the in-memory child owned by this supervisor, never arbitrary PIDs.
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False
            )
        else:
            child.terminate()
        child.wait(timeout=20)


def write_state(nonce, generation, running):
    temporary = CONTROL.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"nonce": nonce, "generation": generation, "ready": running}), encoding="utf-8"
    )
    temporary.replace(CONTROL)


def main():
    assert os.environ.get("NEXUS_E2E_PRODUCTION") == "true"
    assert os.environ.get("NEXUS_E2E_QUEUE_ONLY") == "true"
    assert not ready("http://127.0.0.1:8001/health/ready"), "Isolated API port already occupied"
    assert not ready("http://127.0.0.1:3001"), "Isolated web port already occupied"
    CONTROL.parent.mkdir(parents=True, exist_ok=True)
    COMMAND.unlink(missing_ok=True)
    nonce, generation, api, web = str(uuid.uuid4()), 0, None, None
    env = os.environ.copy()
    env["API_INTERNAL_URL"] = "http://127.0.0.1:8001"
    env["NEXUS_NEXT_DIR"] = os.environ.get("NEXUS_E2E_PRODUCTION_DIR", ".next")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        while True:
            if json.loads(LEDGER.read_text(encoding="utf-8")).get("halt"):
                return
            if api is None:
                api_env = env | {"NEXUS_E2E_PRESERVE_DATA": "true" if generation else "false"}
                api = subprocess.Popen(
                    [sys.executable, "tests/e2e/serve_api.py"],
                    cwd=ROOT,
                    env=api_env,
                    creationflags=flags,
                )
                deadline = time.monotonic() + 90
                while not ready("http://127.0.0.1:8001/health/ready"):
                    assert api.poll() is None, "Isolated API exited"
                    assert time.monotonic() < deadline, "API readiness timeout"
                    time.sleep(0.2)
                if web is None:
                    command = (
                        [
                            "pwsh",
                            "-NoProfile",
                            "-Command",
                            "pnpm --dir apps/web exec next start --hostname 127.0.0.1 --port 3001",
                        ]
                        if os.name == "nt"
                        else [
                            "pnpm",
                            "--dir",
                            "apps/web",
                            "exec",
                            "next",
                            "start",
                            "--hostname",
                            "127.0.0.1",
                            "--port",
                            "3001",
                        ]
                    )
                    web = subprocess.Popen(command, cwd=ROOT, env=env, creationflags=flags)
                deadline = time.monotonic() + 60
                while not ready("http://127.0.0.1:3001"):
                    assert web.poll() is None, "Isolated web exited"
                    assert time.monotonic() < deadline, "Web readiness timeout"
                    time.sleep(0.2)
                generation += 1
                write_state(nonce, generation, True)
            assert api.poll() is None and web.poll() is None, "Unexpected supervised service exit"
            if COMMAND.exists():
                command = json.loads(COMMAND.read_text(encoding="utf-8"))
                COMMAND.unlink()
                assert command.get("nonce") == nonce and command.get("action") in {"api", "all"}
                write_state(nonce, generation, False)
                if command["action"] == "all":
                    stop(web)
                    web = None
                stop(api)
                api = None
            time.sleep(0.1)
    finally:
        stop(web)
        stop(api)
        CONTROL.unlink(missing_ok=True)
        COMMAND.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
