"""Export only public OpenAPI schemas, never settings or credentials."""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps" / "api"))
from nexus.main import app  # noqa: E402

target = root / "packages" / "contracts" / "openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print("Exported public OpenAPI contract.")
