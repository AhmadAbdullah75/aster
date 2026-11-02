"""Stop the native test worker on a new real provider quota error, without logging secrets."""

import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/prepublication"
LOGS = [
    ROOT / ".data/logs/worker.err.log",
    ROOT / ".data/logs/prepublication-live.err.log",
]


def fresh_log_text(positions):
    chunks = []
    for path, position in positions.items():
        if not path.exists():
            continue
        if path.stat().st_size < position:
            position = 0
        with path.open("rb") as stream:
            stream.seek(position)
            chunks.append(stream.read().decode("utf-8", errors="replace"))
            positions[path] = stream.tell()
    return "\n".join(chunks)


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if json.loads((TARGET / "results.json").read_text()).get("halt"):
        return
    positions = {path: path.stat().st_size if path.exists() else 0 for path in LOGS}
    deadline = time.monotonic() + 12 * 3600
    while time.monotonic() < deadline and not (TARGET / "quota-watch.stop").exists():
        if (TARGET / "quota-stop.json").exists():
            return
        fresh = fresh_log_text(positions)
        if fresh:
            if re.search(
                r"HTTP/\S+ 429\b|\b429\s+RESOURCE_EXHAUSTED\b|quota.{0,30}exceeded|RESOURCE_EXHAUSTED|Tavily quota or rate limit reached",
                fresh,
                re.I,
            ):
                evidence = "Real Gemini provider quota/rate-limit failure detected in the new worker log (HTTP 429 / resource exhausted). Testing stopped immediately; update GEMINI_API_KEY directly in root .env and explicitly resume. No replacement provider was selected."
                case_file = TARGET / "active-live-case.txt"
                case_id = case_file.read_text().strip() if case_file.exists() else ""
                if re.fullmatch(r"[A-Z][A-Z0-9]*-\d+", case_id):
                    subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts/prepublication_results.py"),
                            "record",
                            "--ids",
                            case_id,
                            "--result",
                            "B",
                            "--evidence",
                            evidence,
                        ],
                        check=True,
                        capture_output=True,
                    )
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts/prepublication_results.py"),
                        "halt-quota",
                        "--evidence",
                        evidence,
                    ],
                    check=True,
                    capture_output=True,
                )
                stop_script = r"""
$ErrorActionPreference = 'Stop'
$quotaRecords = Get-Content -LiteralPath '.data/processes.json' -Raw | ConvertFrom-Json
foreach ($quotaRecord in $quotaRecords) {
  if ($quotaRecord.service -ne 'worker') { continue }
  $quotaProcess = Get-Process -Id $quotaRecord.id -ErrorAction SilentlyContinue
  $quotaInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($quotaRecord.id)" -ErrorAction SilentlyContinue
  $quotaTime = if ($quotaRecord.start -is [DateTime]) { $quotaRecord.start.ToUniversalTime() } else { [DateTimeOffset]::Parse([string]$quotaRecord.start).UtcDateTime }
  $quotaServicePath = Join-Path (Get-Location) 'scripts/service.ps1'
  if ($quotaProcess -and $quotaInfo.CommandLine -and $quotaInfo.CommandLine.Contains($quotaServicePath) -and ([Math]::Abs(($quotaProcess.StartTime.ToUniversalTime() - $quotaTime).TotalSeconds) -lt 2)) {
    & taskkill /PID $quotaRecord.id /T /F | Out-Null
  }
}
"""
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", stop_script], cwd=ROOT, capture_output=True
                )
                (TARGET / "quota-stop.json").write_text(
                    json.dumps(
                        {
                            "time": datetime.now(UTC).isoformat(),
                            "case": case_id,
                            "reason": "Real provider quota/rate-limit failure; raw provider log omitted to avoid secrets.",
                            "native_worker_stop_command_succeeded": result.returncode == 0,
                        },
                        indent=2,
                    )
                    + "\n"
                )
                print(
                    "QUOTA_STOP: testing halted; see PREPUBLICATION_RESULTS.md. Update .env directly.",
                    flush=True,
                )
                return
        time.sleep(0.25)


if __name__ == "__main__":
    main()
