"""Record observed local health/SQL timings without provider calls or user data."""

import json
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import text

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import engine  # noqa: E402

metrics = {}
with engine.connect() as connection:
    samples = []
    for _ in range(20):
        start = time.perf_counter()
        connection.execute(text("SELECT 1"))
        samples.append((time.perf_counter() - start) * 1000)
    metrics["database_select_1_ms_mean"] = round(sum(samples) / len(samples), 2)
with httpx.Client() as client:
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        response = client.get("http://127.0.0.1:8000/health/ready")
        response.raise_for_status()
        samples.append((time.perf_counter() - start) * 1000)
    metrics["readiness_http_ms_mean"] = round(sum(samples) / len(samples), 2)
(root / "artifacts").mkdir(exist_ok=True)
(root / "artifacts/local-timings.json").write_text(json.dumps(metrics, indent=2))
print(json.dumps(metrics))
