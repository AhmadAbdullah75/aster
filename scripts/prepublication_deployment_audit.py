"""Read local deployment safety metadata without printing credentials or Docker environment."""

import json
import subprocess
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
values = dotenv_values(ROOT / ".env")
password = str(values.get("POSTGRES_PASSWORD", ""))
secret = str(values.get("SESSION_SECRET", ""))
url = str(values["DATABASE_URL"]).replace("postgresql+psycopg://", "postgresql://")
report = {
    "scope": "Local development configuration, not HTTPS staging certification.",
    "database_password_nondefault_minimum32chars": len(password) >= 32 and "GENERATE" not in password,
    "session_secret_nondefault_minimum32chars": len(secret) >= 32 and "GENERATE" not in secret,
    "app_origin_loopback": str(values.get("APP_ORIGIN", "")).startswith(("http://127.0.0.1:", "http://localhost:")),
}
with psycopg.connect(url) as connection:
    row = connection.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    report["runtime_role"] = dict(zip(["superuser", "create_database", "create_role", "bypass_rls"], row, strict=True))
    report["least_privilege_runtime"] = not any(row)
containers = {}
for name in ["nexus-postgres-1", "nexus-publication-api-1", "nexus-publication-worker-1", "nexus-publication-web-1"]:
    result = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.LogConfig}}|{{.HostConfig.RestartPolicy.Name}}|{{json .HostConfig.PortBindings}}", name], capture_output=True, text=True, check=True)
    logging, restart, bindings = result.stdout.strip().split("|", 2)
    containers[name] = {"logging": json.loads(logging), "restart_policy": restart, "published_ports": json.loads(bindings)}
report["containers"] = containers
(ROOT / "artifacts/prepublication/deployment-local-audit.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
