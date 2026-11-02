"""Request a restart only from the running isolated test supervisor."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".data/e2e/workspace-control.json"
COMMAND = ROOT / ".data/e2e/workspace-command.json"
assert sys.argv[1] in {"api", "all"}
state = json.loads(CONTROL.read_text(encoding="utf-8"))
assert state["ready"]
temporary = COMMAND.with_suffix(".tmp")
temporary.write_text(json.dumps({"nonce": state["nonce"], "action": sys.argv[1]}), encoding="utf-8")
temporary.replace(COMMAND)
deadline = time.monotonic() + 100
while time.monotonic() < deadline:
    current = json.loads(CONTROL.read_text(encoding="utf-8"))
    if current["generation"] > state["generation"] and current["ready"]:
        print(
            json.dumps(
                {
                    "before": state["generation"],
                    "after": current["generation"],
                    "restarted": sys.argv[1],
                }
            )
        )
        break
    time.sleep(0.2)
else:
    raise TimeoutError("Isolated workspace restart did not become ready")
