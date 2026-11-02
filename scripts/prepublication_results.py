"""Track the supplied pre-publication plan without turning old evidence into new passes."""

import argparse
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "prepublication-test-plan.md"
STATE = ROOT / "artifacts" / "prepublication" / "results.json"
REPORT = ROOT / "PREPUBLICATION_RESULTS.md"


def render(state):
    counts = Counter(case["result"] for case in state["cases"].values())
    lines = [
        "# Aster pre-publication execution results",
        "",
        "Source: [the supplied plan](docs/prepublication-test-plan.md). This is a new execution ledger; earlier audit results are not new passes.",
        "",
        f"Last updated: {state['updated']}. Target: native production http://localhost:3000.",
        "",
        "Run sections in order. Environment checks precede smoke; all smoke cases must pass before proceeding. Stop immediately on a real provider quota failure.",
        "",
        "[P] passed; [F] failed; [B] blocked; [ ] not run. A mapping to an older test does not itself count as a pass.",
        "",
        f"Counts: {counts['P']} passed, {counts['F']} failed, {counts['B']} blocked, {counts[' ']} not run; {len(state['cases'])} tracked cases.",
        "",
        "**Release status: NOT APPROVED.** This report does not provide the owner's release/signature or create a release tag.",
        "",
    ]
    if state.get("halt"):
        lines += ["## Execution stopped", "", state["halt"], ""]
    if state.get("external_blocker"):
        lines += ["## External execution blocker", "", state["external_blocker"], ""]
    lines += [
        "## External prerequisites",
        "",
        "HTTPS staging/domain/certificate, real phone/Safari access, clean-machine restore/setup and provider billing confirmation cannot be inferred from native browser tests. Record these as blocked if reached without the required environment. Destructive/load/fault tests belong in isolated test environments, not existing user data.",
        "",
        "## Results by case",
        "",
        "| ID | Priority | Result | Evidence / reason |",
        "| --- | --- | --- | --- |",
    ]
    for key, case in state["cases"].items():
        evidence = (
            case.get("evidence", "Not executed in this run.").replace("|", "\\|").replace("\n", " ")
        )
        lines.append(f"| {key} | {case['priority']} | [{case['result']}] | {evidence} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plan_cases(content):
    cases = {}
    for case_id, priority in re.findall(
        r"^\|\s*([A-Z][A-Z0-9]*-\d+)\s*\|\s*(P[012])\s*\|", content, re.M
    ):
        assert case_id not in cases, case_id
        cases[case_id] = {"priority": priority, "result": " "}
    for case_id, priority in re.findall(r"\*\*(E2E-\d+):[^\n]+\((P[012])\)\*\*", content):
        cases[case_id] = {"priority": priority, "result": " "}
    return cases


def mutate():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "sync-plan",
            "record",
            "halt-quota",
            "block-external",
            "clear-external",
            "show",
        ],
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument("--ids", default="")
    parser.add_argument("--result", choices=["P", "F", "B", " "], default="P")
    parser.add_argument("--evidence", default="")
    args = parser.parse_args()
    if args.command == "init":
        if STATE.exists():
            raise SystemExit("Existing execution ledger preserved; use record/show.")
        assert args.source and args.source.is_file()
        content = args.source.read_text(encoding="utf-8-sig")
        PLAN.write_text(content, encoding="utf-8")
        state = {"cases": plan_cases(content)}
    else:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    if args.command == "sync-plan":
        # Add omitted IDs without resetting evidence, results or a quota halt.
        state["cases"] = {
            key: state["cases"].get(key, case)
            for key, case in plan_cases(PLAN.read_text(encoding="utf-8-sig")).items()
        } | {key: case for key, case in state["cases"].items()}
    if args.command == "record":
        if state.get("halt"):
            raise SystemExit(
                "Quota stop is active. Resume only after the owner updates configuration and authorizes continuation."
            )
        for case_id in args.ids.split(","):
            assert case_id in state["cases"], case_id
            state["cases"][case_id].update(result=args.result, evidence=args.evidence)
    if args.command == "halt-quota":
        assert args.evidence
        state["halt"] = args.evidence
    if args.command == "block-external":
        assert args.evidence
        state["external_blocker"] = args.evidence
    if args.command == "clear-external":
        assert args.evidence, "Record the verified recovery before resuming tests."
        state.pop("external_blocker", None)
        state["external_recovery"] = args.evidence
    state["updated"] = datetime.now(UTC).isoformat()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)
    render(state)
    print(
        f"Report saved: {REPORT}; {len(state['cases'])} cases; quota stop: {bool(state.get('halt'))}"
    )


def main():
    # The quota watcher and execution recorder are separate processes. Serialize
    # their read/update/replace operations so a pass cannot overwrite a quota halt.
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.with_suffix(".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            mutate()
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
