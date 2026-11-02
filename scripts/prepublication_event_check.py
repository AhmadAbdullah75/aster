"""Check actual live-run SSE responses locally for configured secrets/private fields."""

import json
from collections import Counter
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
assert not json.loads((ROOT / "artifacts/prepublication/results.json").read_text()).get("halt")
values = dotenv_values(ROOT / ".env")
secrets = [
    str(values[key]).encode()
    for key in ["GEMINI_API_KEY", "OPENAI_API_KEY", "SESSION_SECRET"]
    if values.get(key)
]
private = {
    "api_key",
    "gemini_api_key",
    "openai_api_key",
    "session_secret",
    "password_hash",
    "token_hash",
    "reasoning",
    "thoughts",
    "system_prompt",
}


def private_keys(value):
    if isinstance(value, dict):
        return any(key.lower() in private or private_keys(item) for key, item in value.items())
    return isinstance(value, list) and any(private_keys(item) for item in value)


evidence = []
for email, threads in [
    (
        "nexus-smoke-publication-20261024a@example.com",
        ["07961ff6-cf4c-491d-9494-09310fdd07a2", "c807daa9-72f1-443f-9b1a-5a82654e3506"],
    ),
    (
        "nexus-empty-publication-20261024a@example.com",
        ["e9c3c463-1de4-4f30-b82d-01a337fa0a61", "8b42debc-2b41-4962-9f6f-563bc5692b8c"],
    ),
]:
    with httpx.Client(
        base_url="http://localhost:3000", headers={"origin": "http://localhost:3000"}, timeout=20
    ) as client:
        client.post(
            "/api/auth/login", json={"email": email, "password": "synthetic-publication-password"}
        ).raise_for_status()
        try:
            for thread in threads:
                history = client.get(f"/api/conversations/{thread}/history")
                history.raise_for_status()
                for run in history.json()["runs"]:
                    assert run["status"] == "completed"
                    response = client.get(f"/api/runs/{run['id']}/events")
                    response.raise_for_status()
                    assert "text/event-stream" in response.headers["content-type"]
                    assert not any(secret in response.content for secret in secrets), (
                        "Configured secret in SSE response"
                    )
                    events = [
                        json.loads(line[6:])
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]
                    assert events and not private_keys(events), (
                        "Private/hidden-reasoning field in SSE"
                    )
                    evidence.append(
                        {
                            "thread": thread,
                            "run": run["id"],
                            "event_count": len(events),
                            "types": dict(Counter(event["type"] for event in events)),
                            "configured_secret_matches": 0,
                            "private_reasoning_fields": 0,
                        }
                    )
        finally:
            client.post("/api/auth/logout").raise_for_status()

result = {
    "scope": "Actual completed Gemini calculator, PDF, web and selected-source SSE HTTP responses; known configured secrets compared only locally. Hidden-reasoning/private JSON fields checked. Not proof against every future model output.",
    "runs": evidence,
}
(ROOT / "artifacts/prepublication/STR-11-network.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(
    f"{len(evidence)} actual live-run SSE responses checked; no configured secret matches or hidden/private reasoning fields."
)
