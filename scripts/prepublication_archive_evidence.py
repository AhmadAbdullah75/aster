"""Copy a completed full run's custom reports before another run reuses filenames."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/prepublication"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    assert re.fullmatch(r"[a-zA-Z0-9-]+", args.run_id)
    log = TARGET / (args.run_id + ".log")
    assert "All deterministic verification commands passed." in log.read_text()
    stamp = log.stat()
    start, end = getattr(stamp, "st_birthtime", stamp.st_ctime), stamp.st_mtime
    output = TARGET / args.run_id / "custom-evidence"
    assert output.parent.is_dir() and not output.exists()
    output.mkdir()
    manifest = {}
    for path in sorted(TARGET.iterdir()):
        state = json.loads((TARGET / "results.json").read_text())
        if state.get("halt") or state.get("external_blocker"):
            raise SystemExit(75)
        if not path.is_file() or path.is_symlink() or path.suffix not in {".json", ".png"}:
            continue
        if path.name.startswith(("quota-", "results", "live-flow-rate")):
            continue
        if not start <= path.stat().st_mtime <= end:
            continue
        shutil.copy2(path, output / path.name)
        manifest[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": "Root custom reports/screenshots modified during this successful run; Playwright-owned output is already in the run's trace folders.",
                "files": manifest,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Preserved {len(manifest)} custom reports/screenshots for {args.run_id}.")


if __name__ == "__main__":
    main()
