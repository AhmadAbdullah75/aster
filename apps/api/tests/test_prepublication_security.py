"""Pre-publication origin, two-account resource and search boundaries."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import register
from fastapi.testclient import TestClient
from nexus.config import settings
from nexus.db import transaction
from nexus.main import app
from nexus.models import (
    Chunk,
    Conversation,
    Document,
    Note,
    Project,
    Proposal,
    Run,
    Task,
    User,
    now,
)
from sqlalchemy import select


@pytest.mark.parametrize(
    "case_id,origin,accepted",
    [
        ("SEC-01", None, False),
        ("SEC-02", "https://evil.com", False),
        ("SEC-03", "http://localhost.evil.com:3000", False),
        ("SEC-04", "http://127.0.0.1:3000", True),
        ("SEC-05", "http://127.0.0.1:3001", False),
        ("SEC-06", "https://localhost:3000", False),
        ("SEC-07", "http://[::1]:3000", True),
    ],
)
def test_origin_rules(client, monkeypatch, case_id, origin, accepted):
    monkeypatch.setattr(settings, "app_origin", "http://localhost:3000")
    if origin is None:
        client.headers.pop("origin")
        headers = {}
    else:
        headers = {"origin": origin}
    response = client.post(
        "/auth/register",
        json={"email": "origin@example.com", "password": "synthetic-origin-password"},
        headers=headers,
    )
    assert response.status_code == (200 if accepted else 403), (case_id, response.text)
    if not accepted:
        assert isinstance(response.json()["detail"], str)


def test_SEC_08_read_requests_need_no_origin(client):
    register(client)
    client.headers.pop("origin")
    assert client.get("/me").status_code == 200
    assert client.get("/projects").status_code == 200


def test_SEC_09_remote_config_does_not_accept_loopback(client, monkeypatch):
    monkeypatch.setattr(settings, "app_origin", "https://staging.example.com")
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000", "https://other.example.com"):
        assert (
            client.post(
                "/auth/login",
                json={"email": "nobody@example.com", "password": "synthetic-password"},
                headers={"origin": origin},
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "synthetic-password"},
            headers={"origin": settings.app_origin},
        ).status_code
        == 401
    )


@pytest.fixture
def foreign_resources(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-unused-key-no-worker")
    owner = register(client)
    project = client.post("/projects", json={"title": "Private Cedar Lantern"}).json()
    thread = client.post("/conversations", json={"project_id": project["id"]}).json()
    task = client.post(
        "/tasks", json={"title": "Private Cedar Lantern task", "project_id": project["id"]}
    ).json()
    note = client.post(
        "/notes",
        json={
            "title": "Private Cedar Lantern note",
            "content": "Synthetic private evidence.",
            "project_id": project["id"],
        },
    ).json()
    memory = client.post(
        "/memories",
        json={"title": "Private Cedar Lantern memory", "content": "Synthetic private preference."},
    ).json()
    doc_result = client.post(
        "/documents",
        data={"project_id": project["id"]},
        files={
            "file": ("private.pdf", b"%PDF-1.7 Synthetic access-control fixture", "application/pdf")
        },
    )
    assert doc_result.status_code == 202
    document = doc_result.json()
    with transaction() as db:
        doc = db.get(Document, document["id"])
        doc.status = "ready"
        doc.embedding_model = settings.embedding_model
        doc.embedding_dimensions = 1536
        chunk = Chunk(
            user_id=owner["id"],
            document_id=doc.id,
            position=0,
            section="Private",
            page=1,
            content="Private Cedar Lantern evidence.",
            embedding=[0.1] * 1536,
        )
        db.add(chunk)
        db.flush()
        chunk_id = chunk.id
    run_result = client.post(
        f"/conversations/{thread['id']}/runs",
        json={"message": "Synthetic owned run; no worker is launched."},
    )
    assert run_result.status_code == 202
    run = run_result.json()
    with transaction() as db:
        db.get(Run, run["id"]).status = "waiting"
        proposal = Proposal(
            user_id=owner["id"],
            conversation_id=thread["id"],
            run_id=run["id"],
            call_id="synthetic-call",
            action="tasks.create",
            payload={"items": [{"title": "Private proposed task"}]},
            expires_at=now() + timedelta(days=7),
            idempotency_key="synthetic-private-proposal",
        )
        db.add(proposal)
        db.flush()
        proposal_id = proposal.id
    assert client.get(f"/sources/{chunk_id}").status_code == 200
    assert client.get(f"/documents/{document['id']}/preview?download=true").status_code == 200
    thread = client.get(f"/conversations/{thread['id']}").json()
    attacker = register(client, "bob@example.com")
    own_thread = client.post("/conversations", json={}).json()
    return {
        "owner": owner,
        "attacker": attacker,
        "projects": project,
        "conversations": thread,
        "tasks": task,
        "notes": note,
        "memories": memory,
        "documents": document,
        "run": run,
        "chunk": chunk_id,
        "proposal": proposal_id,
        "own_thread": own_thread,
    }


@pytest.mark.parametrize(
    "case_id,kind",
    [
        ("IDOR-01", "conversations"),
        ("IDOR-04", "projects"),
        ("IDOR-09", "tasks"),
        ("IDOR-10", "notes"),
    ],
)
def test_foreign_crud(client, foreign_resources, case_id, kind):
    resource = foreign_resources[kind]
    target = f"/{kind}/{resource['id']}"
    assert client.get(target).status_code == 404
    update = {"title": "Attempted overwrite", "version": resource["version"]}
    if kind == "notes":
        update["content"] = "Attempted overwrite"
    assert client.put(target, json=update).status_code == 404
    assert client.delete(target, params={"version": resource["version"]}).status_code == 404
    model = {"conversations": Conversation, "projects": Project, "tasks": Task, "notes": Note}[kind]
    with transaction() as db:
        original = db.get(model, resource["id"])
        assert original.title == resource["title"]
        assert original.user_id == foreign_resources["owner"]["id"]
        if kind == "conversations":
            assert original.archived is False
    if kind == "conversations":
        assert (
            client.put(
                target,
                json={"title": "Attempt archive", "archived": True, "version": resource["version"]},
            ).status_code
            == 404
        )


@pytest.mark.parametrize("case_id,suffix", [("IDOR-06", "?download=true"), ("IDOR-07", "")])
def test_foreign_pdf_bytes(client, foreign_resources, case_id, suffix):
    assert (
        client.get(f"/documents/{foreign_resources['documents']['id']}/preview{suffix}").status_code
        == 404
    )


def test_IDOR_02_IDOR_03_IDOR_08_IDOR_12_IDOR_13(client, foreign_resources):
    resources = foreign_resources
    for target in (
        f"/conversations/{resources['conversations']['id']}/history",
        f"/runs/{resources['run']['id']}",
        f"/runs/{resources['run']['id']}/events",
        f"/sources/{resources['chunk']}",
        f"/proposals/{resources['proposal']}",
    ):
        assert client.get(target).status_code == 404
    assert (
        client.post(
            f"/proposals/{resources['proposal']}/decision", json={"approve": True, "version": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/conversations/{resources['conversations']['id']}/runs",
            json={"message": "Attempt foreign thread"},
        ).status_code
        == 404
    )


def test_IDOR_05_IDOR_11_IDOR_14_IDOR_15_IDOR_16_IDOR_17(client, foreign_resources):
    resources = foreign_resources
    for kind in ("projects", "tasks", "notes", "memories", "documents"):
        assert client.get(f"/{kind}").json() == []
        assert client.get(f"/{kind}?q=Cedar").json() == []
    threads = client.get("/conversations").json()
    assert [item["id"] for item in threads] == [resources["own_thread"]["id"]]
    memory = resources["memories"]
    assert (
        client.put(
            f"/memories/{memory['id']}",
            json={"title": "Attempt", "content": "Attempt", "version": memory["version"]},
        ).status_code
        == 404
    )
    assert client.delete(f"/memories/{memory['id']}?version={memory['version']}").status_code == 404
    assert client.delete(f"/documents/{resources['documents']['id']}?version=1").status_code == 404
    assert client.post(f"/documents/{resources['documents']['id']}/retry").status_code == 404
    assert (
        client.post(
            f"/conversations/{resources['own_thread']['id']}/runs",
            json={
                "message": "Attempt selected document",
                "document_ids": [resources["documents"]["id"]],
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/tasks", json={"title": "Attempt", "project_id": resources["projects"]["id"]}
        ).status_code
        == 404
    )
    # Reauthenticate as owner and prove all attempted mutations left records intact.
    assert (
        client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "synthetic-test-password"},
        ).status_code
        == 200
    )
    for kind in ("projects", "tasks", "notes"):
        assert (
            client.get(f"/{kind}/{resources[kind]['id']}").json()["title"]
            == resources[kind]["title"]
        )
    assert len(client.get("/documents").json()) == 1
    assert len(client.get("/memories").json()) == 1


def test_SQLI_01_SQLI_02_search_and_ids(client):
    register(client)
    for kind in ("projects", "tasks", "notes", "memories", "documents", "conversations"):
        assert client.get(f"/{kind}", params={"q": "' OR 1=1 --"}).json() == []
    for kind in ("projects", "tasks", "notes", "conversations"):
        assert client.get(f"/{kind}/1; DROP TABLE users").status_code == 404
    with transaction() as db:
        assert db.scalar(select(User.email)) == "alice@example.com"


@pytest.mark.asyncio
async def test_SQLI_03_special_full_text_search(client, foreign_resources, monkeypatch):
    from nexus import documents

    async def embed_without_external_request(texts):
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(documents, "embed", embed_without_external_request)
    for query in ("& | ! ( ) : *", '"unclosed', "a:* & !b", "' OR 1=1 --"):
        result = await documents.search(foreign_resources["owner"]["id"], query, None, [])
        assert isinstance(result["sources"], list)
        assert len(result["sources"]) <= 8


@pytest.mark.asyncio
async def test_PI_07_tool_arguments_cannot_replace_runtime_identity(client, foreign_resources):
    from nexus.tools import read_tool

    context = SimpleNamespace(user_id=foreign_resources["attacker"]["id"], project_id=None)
    for tool in ("list_tasks", "search_notes"):
        result = await read_tool(
            tool, {"query": "Cedar", "user_id": foreign_resources["owner"]["id"]}, context
        )
        assert result["items"] == []
    result = client.post(
        f"/conversations/{foreign_resources['own_thread']['id']}/runs",
        json={"message": "Attempt forged identity", "user_id": foreign_resources["owner"]["id"]},
    )
    assert result.status_code == 422


def test_SECR_05_unhandled_failure_does_not_expose_exception(client, monkeypatch):
    from nexus import main

    register(client)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic internal diagnostic; must never reach the client")

    monkeypatch.setattr(main, "save", fail)
    with TestClient(
        app, headers={"origin": settings.app_origin}, raise_server_exceptions=False
    ) as request:
        request.cookies.update(client.cookies)
        response = request.post("/projects", json={"title": "Synthetic failure"})
        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        assert "diagnostic" not in response.text
