"""Concurrency of temporary test ledgers only; never halt the actual execution ledger."""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHILD = """
import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location('isolated_results', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
target = pathlib.Path(sys.argv[2]).resolve()
module.STATE = target / 'results.json'
module.REPORT = target / 'report.md'
module.PLAN = target / 'plan.md'
args = sys.argv[3:]
if args[0] == 'slow-record':
    original = module.json.loads
    def slow(value, *a, **kw):
        result = original(value, *a, **kw)
        (target / 'read-ready').write_text('ready')
        time.sleep(1)
        return result
    module.json.loads = slow
    args[0] = 'record'
sys.argv = ['isolated_results', *args]
module.main()
"""


def initial(tmp_path):
    state = {
        "cases": {f"LOCK-{number}": {"priority": "P0", "result": " "} for number in range(8)},
        "updated": "fixture",
    }
    (tmp_path / "results.json").write_text(json.dumps(state), encoding="utf-8")
    return [
        sys.executable,
        "-c",
        CHILD,
        str(ROOT / "scripts/prepublication_results.py"),
        str(tmp_path),
    ]


def finish(process):
    output, error = process.communicate(timeout=20)
    assert process.returncode == 0, error or output


def test_parallel_updates_preserve_all_cases(tmp_path):
    command = initial(tmp_path)
    processes = [
        subprocess.Popen(
            [
                *command,
                "record",
                "--ids",
                f"LOCK-{number}",
                "--evidence",
                "Synthetic concurrent update",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for number in range(8)
    ]
    for process in processes:
        finish(process)
    result = json.loads((tmp_path / "results.json").read_text())
    assert all(case["result"] == "P" for case in result["cases"].values())


def test_plan_sync_adds_digit_containing_ids_without_resetting_halt_or_results(tmp_path):
    command = initial(tmp_path)
    (tmp_path / "plan.md").write_text("| LOCK-0 | P0 | Existing |\n| A11Y-01 | P1 | Keyboard |\n")
    state = json.loads((tmp_path / "results.json").read_text())
    state["cases"]["LOCK-0"].update(result="P", evidence="Preserve this evidence")
    state["halt"] = "SIMULATED temporary-ledger halt"
    (tmp_path / "results.json").write_text(json.dumps(state))
    subprocess.run([*command, "sync-plan"], check=True, capture_output=True, text=True)
    result = json.loads((tmp_path / "results.json").read_text())
    assert result["halt"] == state["halt"]
    assert result["cases"]["LOCK-0"] == state["cases"]["LOCK-0"]
    assert result["cases"]["A11Y-01"]["result"] == " "
    assert len(result["cases"]) == 9


def test_quota_halt_cannot_be_overwritten_by_inflight_record(tmp_path):
    command = initial(tmp_path)
    writer = subprocess.Popen(
        [*command, "slow-record", "--ids", "LOCK-0", "--evidence", "Synthetic delayed record"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not (tmp_path / "read-ready").exists():
        assert time.monotonic() < deadline
        time.sleep(0.02)
    halt = subprocess.Popen(
        [*command, "halt-quota", "--evidence", "SIMULATED temporary-ledger halt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    finish(writer)
    finish(halt)
    result = json.loads((tmp_path / "results.json").read_text())
    assert result["halt"] == "SIMULATED temporary-ledger halt"
    assert result["cases"]["LOCK-0"]["result"] == "P"
