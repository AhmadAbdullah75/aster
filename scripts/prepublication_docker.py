"""Prepare a separate localhost Compose test stack without loading real API keys."""

import json
import secrets
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".data/prepublication-docker"
TARGET.mkdir(parents=True, exist_ok=True)
env_path = TARGET / "test.env"
if not env_path.exists():
    values = {
        "POSTGRES_USER": "nexus_publication",
        "POSTGRES_DB": "nexus_publication",
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "SESSION_SECRET": secrets.token_hex(48),
        "AI_PROVIDER": "gemini",
        "GEMINI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "FREE_ONLY": "true",
        "WEB_BACKEND": "ddgs",
        "APP_ORIGIN": "http://localhost:3002",
    }
    env_path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
for name, service in compose["services"].items():
    service.pop("profiles", None)
    if "build" in service:
        service["build"]["context"] = str(ROOT)
    if "env_file" in service:
        service["env_file"] = str(env_path)
    if name in {"api", "worker"}:
        service["environment"].update(GEMINI_API_KEY="", OPENAI_API_KEY="")
    if name == "postgres":
        service["ports"] = ["127.0.0.1:5435:5432"]
    if name == "web":
        service["ports"] = ["127.0.0.1:3002:3000"]
(TARGET / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")
print("Isolated nexus-publication stack prepared on web3002/database5435; real API keys excluded.")
