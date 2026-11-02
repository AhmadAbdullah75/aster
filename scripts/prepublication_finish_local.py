"""Finish the already-started load measurement, then run three serial full checks.

This is one finite local test job, not a scheduler. It stops at the first failure.
Provider calls are disabled by check.ps1. Publication remains a separate decision.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from prepublication_native_load import validate_sample_coverage

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/prepublication"
STATUS = ARTIFACTS / "remaining-local-20261028.json"


def check_stop():
    ledger = json.loads((ARTIFACTS / "results.json").read_text(encoding="utf-8"))
    assert not (ledger.get("halt") or ledger.get("external_blocker")), "Execution stop active"


def hashes():
    files = [
        *Path(ROOT / "apps/api/nexus").glob("*.py"),
        *[
            p
            for p in (ROOT / "apps/web/src").rglob("*")
            if p.suffix in {".ts", ".tsx", ".css", ".svg"}
        ],
        ROOT / "apps/web/next.config.ts",
    ]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(files)
    }


def main():
    assert not STATUS.exists(), "Preserve previous orchestration evidence"
    state = {"stage": "waiting_for_load", "completed_runs": [], "complete": False}

    def save():
        STATUS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    baseline = hashes()
    reference = json.loads((ARTIFACTS / "full-check-05/product-source.json").read_text())
    assert baseline == {k.replace("\\", "/"): v for k, v in reference["files"].items()}
    run_ids = ["full-check-07", "full-check-08", "full-check-09"]
    for run_id in run_ids:
        assert not (ARTIFACTS / run_id).exists() and not (ARTIFACTS / (run_id + ".log")).exists()
    save()
    try:
        load_path = ARTIFACTS / "load_hour_20261028a-native-load/results.json"
        deadline = time.monotonic() + 95 * 60
        while True:
            check_stop()
            assert time.monotonic() < deadline, "Load report did not complete within deadline"
            assert time.time() - load_path.stat().st_mtime < 240, "Load report stopped updating"
            report = json.loads(load_path.read_text())
            if report.get("complete") and report.get("disposable_database_removed"):
                break
            time.sleep(2)
        assert report["hour_completed"] and report["duration_seconds"] >= 3600
        assert report["final"]["failed"] == report["final"]["pending"] == 0
        assert not report["memory_growth_over_128mib"], "Memory growth requires investigation"
        validate_sample_coverage(report["samples"], report["duration_seconds"])
        state["load_report_ready_for_review"] = str(load_path.relative_to(ROOT))
        for run_id in run_ids:
            check_stop()
            assert hashes() == baseline, "Product changed; clean-run sequence stopped"
            state["stage"] = run_id
            save()
            print(f"Starting {run_id}", flush=True)
            subprocess.run(
                [
                    sys.executable,
                    "scripts/prepublication_run.py",
                    "--resource-profile",
                    "bounded",
                    "--log",
                    f"artifacts/prepublication/{run_id}.log",
                    "--",
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    "scripts/check.ps1",
                    "-RunId",
                    run_id,
                ],
                cwd=ROOT,
                check=True,
            )
            check_stop()
            assert hashes() == baseline, "Product changed during full check"
            (ARTIFACTS / run_id / "product-source.json").write_text(
                json.dumps({"files": baseline, "matches_full_check_05": True}, indent=2) + "\n"
            )
            subprocess.run(
                [sys.executable, "scripts/prepublication_archive_evidence.py", run_id],
                cwd=ROOT,
                check=True,
            )
            state["completed_runs"].append(run_id)
            save()
        state.update(stage="ready_for_review", complete=True)
        save()
        print(
            "Three full checks completed. Review evidence before updating acceptance or publishing.",
            flush=True,
        )
    except Exception as error:
        state.update(stage="stopped_for_review", error=str(error))
        save()
        raise


if __name__ == "__main__":
    main()
