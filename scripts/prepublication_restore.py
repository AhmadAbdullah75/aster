"""Exercise DB-only and DB+original-file recovery in a clean local container volume."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".data/prepublication-docker"
BACKUP = TARGET / "backup"
BACKUP.mkdir(exist_ok=True)
base = [
    "docker",
    "compose",
    "-p",
    "nexus-publication",
    "--env-file",
    str(TARGET / "test.env"),
    "-f",
    str(TARGET / "compose.json"),
]
probe = ROOT / "scripts/prepublication_container_probe.py"
reports = {}


def run(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result.stdout.strip()


run([*base, "stop", "worker"])
run(["docker", "cp", str(probe), "nexus-publication-api-1:/tmp/recovery_probe.py"])
reports["seed"] = json.loads(
    run([*base, "exec", "-T", "api", "uv", "run", "python", "/tmp/recovery_probe.py", "seed"])
)
run(
    [
        *base,
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "nexus_publication",
        "-d",
        "nexus_publication",
        "-Fc",
        "-f",
        "/tmp/publication.dump",
    ]
)
run(
    [
        "docker",
        "cp",
        "nexus-publication-postgres-1:/tmp/publication.dump",
        str(BACKUP / "database.dump"),
    ]
)
run([*base, "exec", "-T", "api", "tar", "-czf", "/tmp/originals.tar.gz", "-C", "/data", "blobs"])
run(
    [
        "docker",
        "cp",
        "nexus-publication-api-1:/tmp/originals.tar.gz",
        str(BACKUP / "originals.tar.gz"),
    ]
)
run([*base, "exec", "-T", "postgres", "createdb", "-U", "nexus_publication", "nexus_restore"])
run(
    [
        *base,
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "-U",
        "nexus_publication",
        "-d",
        "nexus_restore",
        "/tmp/publication.dump",
    ]
)
restore = {
    "services": {
        "restore": {
            "image": "nexus-publication-api",
            "env_file": str(TARGET / "test.env"),
            "environment": {
                "DATABASE_URL": "postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/nexus_restore",
                "DATA_DIR": "/data",
                "GEMINI_API_KEY": "",
                "OPENAI_API_KEY": "",
            },
            "volumes": [
                "restore_data:/data",
                {
                    "type": "bind",
                    "source": str(probe),
                    "target": "/tmp/recovery_probe.py",
                    "read_only": True,
                },
                {"type": "bind", "source": str(BACKUP), "target": "/backup", "read_only": True},
            ],
        }
    },
    "networks": {"default": {"external": True, "name": "nexus-publication_default"}},
    "volumes": {"restore_data": {}},
}
config = TARGET / "restore.json"
config.write_text(json.dumps(restore, indent=2))
command = [
    "docker",
    "compose",
    "-p",
    "nexus-publication-recovery",
    "--env-file",
    str(TARGET / "test.env"),
    "-f",
    str(config),
    "run",
    "--rm",
    "--no-deps",
    "restore",
]
reports["db_only"] = json.loads(
    run([*command, "uv", "run", "python", "/tmp/recovery_probe.py", "missing-files"])
)
run([*command, "tar", "-xzf", "/backup/originals.tar.gz", "-C", "/data"])
reports["complete_restore"] = json.loads(
    run([*command, "uv", "run", "python", "/tmp/recovery_probe.py", "verify"])
)
run([*base, "restart", "postgres"])
run([*base, "up", "-d", "--wait", "--wait-timeout", "120"])
reports["after_postgres_restart"] = json.loads(
    run([*base, "exec", "-T", "api", "uv", "run", "python", "/tmp/recovery_probe.py", "verify"])
)
reports["scope"] = (
    "Clean database and new file volume in a separate container; not a separate physical machine or public deployment. Only disposable synthetic Docker data."
)
(ROOT / "artifacts/prepublication/restore-verified.json").write_text(
    json.dumps(reports, indent=2) + "\n"
)
print(json.dumps(reports))
