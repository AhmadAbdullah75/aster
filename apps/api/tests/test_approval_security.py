from datetime import timedelta

from conftest import register
from nexus.actions import propose
from nexus.db import transaction
from nexus.models import Chunk, Document, Proposal, Run, now


def test_proposal_target_tampering_stale_versions_expiry_and_ownership(client, monkeypatch):
    from test_graph import setup_run

    user, thread, run = setup_run(client, monkeypatch)
    first = client.post("/tasks", json={"title": "First task"}).json()
    second = client.post("/tasks", json={"title": "Other target"}).json()
    payload = {"items": [{"id": first["id"], "version": 1, "title": "Approved rename"}]}
    proposal = propose(user["id"], thread["id"], run.id, "update-call", "tasks.update", payload)
    assert (
        propose(user["id"], thread["id"], run.id, "update-call", "tasks.update", payload)["id"]
        == proposal["id"]
    )
    with transaction() as db:
        db.get(Run, run.id).status = "waiting"
    edited = proposal["payload"]
    edited["items"][0]["id"] = second["id"]
    assert (
        client.post(
            "/proposals/" + proposal["id"] + "/decision",
            json={"approve": True, "version": 1, "payload": edited},
        ).status_code
        == 422
    )
    client.put("/tasks/" + first["id"], json={"title": "Changed by user", "version": 1})
    assert (
        client.post(
            "/proposals/" + proposal["id"] + "/decision", json={"approve": True, "version": 1}
        ).status_code
        == 409
    )
    with transaction() as db:
        db.get(Proposal, proposal["id"]).expires_at = now() - timedelta(seconds=1)
    assert (
        client.post(
            "/proposals/" + proposal["id"] + "/decision", json={"approve": False, "version": 1}
        ).status_code
        == 409
    )
    client.post("/auth/logout")
    register(client, "other@example.com")
    assert client.get("/proposals/" + proposal["id"]).status_code == 404
    assert (
        client.post(
            "/proposals/" + proposal["id"] + "/decision", json={"approve": True, "version": 1}
        ).status_code
        == 404
    )


def test_cross_user_document_citation_and_memory_endpoints(client):
    user = register(client)
    memory = client.post(
        "/memories", json={"title": "Private", "content": "User-scoped preference"}
    ).json()
    with transaction() as db:
        doc = Document(
            user_id=user["id"],
            filename="private.pdf",
            blob="synthetic-unread.pdf",
            sha256="synthetic",
            size=10,
            media_type="application/pdf",
            status="ready",
        )
        db.add(doc)
        db.flush()
        chunk = Chunk(
            user_id=user["id"],
            document_id=doc.id,
            content="Private source",
            position=0,
            page=1,
            section="Page 1",
            embedding=[1.0] + [0.0] * 1535,
        )
        db.add(chunk)
        db.flush()
        doc_id, source_id = doc.id, chunk.id
    client.post("/auth/logout")
    register(client, "other@example.com")
    assert client.get("/documents/" + doc_id + "/preview").status_code == 404
    assert client.get("/sources/" + source_id).status_code == 404
    assert client.delete("/documents/" + doc_id + "?version=1").status_code == 404
    assert (
        client.put(
            "/memories/" + memory["id"],
            json={"title": "Attack", "content": "Cannot edit", "version": 1},
        ).status_code
        == 404
    )
    assert client.delete("/memories/" + memory["id"] + "?version=1").status_code == 404
