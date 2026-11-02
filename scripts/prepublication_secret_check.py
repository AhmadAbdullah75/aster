"""Compare configured secret values locally; emit only sanitized findings/counts."""

import json
import subprocess
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    assert not json.loads((ROOT / "artifacts/prepublication/results.json").read_text()).get(
        "halt"
    ), "Quota stop is active"
    values = dotenv_values(ROOT / ".env")
    secrets = [
        str(value).encode()
        for name, value in values.items()
        if value
        and len(str(value)) >= 12
        and ("API_KEY" in name or "SECRET" in name or "PASSWORD" in name or name == "DATABASE_URL")
    ]
    assert secrets, "No configured secret values available for the comparison"
    tracked = (
        subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    groups = {
        "reviewable_source": [ROOT / name for name in tracked if name and (ROOT / name).is_file()],
        "browser_bundles": list((ROOT / "apps/web/.next/static").rglob("*.js")),
        "service_logs": list((ROOT / ".data/logs").glob("*.log")),
    }
    findings = []
    for group, files in groups.items():
        for file in files:
            content = file.read_bytes()
            if any(value in content for value in secrets):
                findings.append({"area": group, "file": str(file.relative_to(ROOT))})
    history = subprocess.check_output(["git", "log", "-p", "--all"], cwd=ROOT)
    if any(value in history for value in secrets):
        findings.append({"area": "git_history", "file": "Git history (secret value omitted)"})
    response_count = 0
    with httpx.Client(
        base_url="http://localhost:3000", headers={"origin": "http://localhost:3000"}, timeout=15
    ) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "email": "nexus-smoke-publication-20261024a@example.com",
                "password": "synthetic-publication-password",
            },
        )
        login.raise_for_status()
        try:
            for endpoint in (
                "/",
                "/api/me",
                "/api/capabilities",
                "/api/projects",
                "/api/conversations",
                "/api/documents",
                "/api/tasks",
                "/api/notes",
                "/api/memories",
                "/api/conversations/663aa892-a692-4d91-bcb5-d78032c969fa/history",
            ):
                response = client.get(endpoint)
                response.raise_for_status()
                response_count += 1
                if any(value in response.content for value in secrets):
                    findings.append({"area": "served_http_response", "file": endpoint})
                if "application/json" in response.headers.get("content-type", ""):

                    def private_fields(value):
                        if isinstance(value, dict):
                            return any(
                                key.lower()
                                in {
                                    "password_hash",
                                    "token_hash",
                                    "session_secret",
                                    "gemini_api_key",
                                    "openai_api_key",
                                    "database_url",
                                }
                                or private_fields(item)
                                for key, item in value.items()
                            )
                        return isinstance(value, list) and any(
                            private_fields(item) for item in value
                        )

                    if private_fields(response.json()):
                        findings.append({"area": "private_response_field", "file": endpoint})
        finally:
            client.post("/api/auth/logout").raise_for_status()
    result = {
        "configured_secret_values": "compared locally; never printed",
        "files_scanned": {group: len(files) for group, files in groups.items()},
        "git_history_scanned": True,
        "served_http_responses_checked": response_count,
        "findings": findings,
        "scope": "Known current configured secrets only; not a complete detector for arbitrary historical credentials.",
    }
    (ROOT / "artifacts/prepublication/secret-scan.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
