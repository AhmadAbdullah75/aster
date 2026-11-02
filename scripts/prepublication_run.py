"""Run a test batch and terminate its own process tree immediately on the quota stop flag."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "artifacts/prepublication/results.json"
GIB = 1024**3
START_RESERVE = 10 * GIB
BOUNDED_START_RESERVE = 6 * GIB
RUN_RESERVE = 5 * GIB


def stopped():
    state = json.loads(LEDGER.read_text(encoding="utf-8"))
    return bool(state.get("halt") or state.get("external_blocker"))


def block_storage(free_bytes, reserve):
    reason = (
        f"Storage safety stop: {free_bytes / GIB:.2f}GiB free on the workspace drive; "
        f"required reserve {reserve / GIB:.0f}GiB. Test command stopped before further disk pressure. "
        "Free space and verify Docker/PostgreSQL before clearing the external blocker. No quota failure inferred."
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepublication_results.py"),
            "block-external",
            "--evidence",
            reason,
        ],
        check=True,
        capture_output=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--resource-profile", choices=["heavy", "bounded"], default="heavy")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    assert command
    target = (ROOT / args.log).resolve()
    assert target.is_relative_to((ROOT / "artifacts/prepublication").resolve())
    if stopped():
        print("TEST_STOP: quota or external execution blocker is active; no test command launched.")
        return 75
    free_bytes = shutil.disk_usage(ROOT).free
    required = START_RESERVE if args.resource_profile == "heavy" else BOUNDED_START_RESERVE
    if free_bytes < required:
        block_storage(free_bytes, required)
        print(
            f"STORAGE_STOP: at least{required / GIB:.0f}GiB free is required for this test batch."
        )
        return 78
    with target.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        while child.poll() is None:
            free_bytes = shutil.disk_usage(ROOT).free
            if free_bytes < RUN_RESERVE and not stopped():
                block_storage(free_bytes, RUN_RESERVE)
            if stopped():
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True
                    )
                else:
                    child.terminate()
                child.wait(timeout=20)
                print("TEST_STOP: this test process tree was terminated; no more tests launched.")
                return 75
            time.sleep(0.2)
    print(f"Test command exited {child.returncode}; log: {target.relative_to(ROOT)}")
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
