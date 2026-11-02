"""DAT-04: inspect private persistence after actual resource deletion paths."""

import json
from pathlib import Path

import pytest
from nexus import documents
from nexus.config import settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import (
    Chunk,
    Conversation,
    Document,
    IngestionJob,
    Message,
    Note,
    Project,
    Proposal,
    Run,
    RunEvent,
    Task,
)
from nexus.worker import process_run
from sqlalchemy import func, select, text
from test_graph import FakeModel, setup_run


@pytest.mark.asyncio
async def test_DAT_04_deletions_remove_private_rows_store_checkpoints_and_originals(
    client, monkeypatch
):
    user, thread, run = setup_run(client, monkeypatch)
    project = client.post("/projects", json={"title": "Deletion audit project"}).json()
    linked = client.put(
        f"/conversations/{thread['id']}",
        json={"title": "Private deletion transcript", "project_id": project["id"], "version": 2},
    )
    assert linked.status_code == 200, linked.text
    for kind in ("tasks", "notes"):
        response = client.post(
            f"/{kind}", json={"title": "Project private data", "project_id": project["id"]}
        )
        assert response.status_code == 200, response.text
    personal_note = client.post("/notes", json={"title": "Preserved personal note"}).json()
    personal_memory = client.post(
        "/memories", json={"title": "Preserved preference", "content": "Personal control data"}
    ).json()
    scoped_memory = client.post(
        "/memories",
        json={
            "title": "Project private memory",
            "content": "Private project preference",
            "project_id": project["id"],
        },
    )
    assert scoped_memory.status_code == 200, scoped_memory.text
    upload = client.post(
        "/documents",
        data={"project_id": project["id"]},
        files={"file": ("private.txt", b"Private deletion audit source", "text/plain")},
    )
    assert upload.status_code == 202, upload.text
    document_id = upload.json()["id"]

    async def fake_embedding(texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]

    monkeypatch.setattr(documents, "embed", fake_embedding)
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_test"
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == document_id))
        job.status, job.worker_id = "processing", "deletion-audit-ingestion"
        doc = db.get(Document, document_id)
        doc.status = "processing"
        original = (settings.blobs / doc.blob).resolve()
        assert original.is_relative_to(settings.blobs.resolve())
    await documents.ingest(document_id, "deletion-audit-ingestion")
    assert original.is_file()
    with transaction() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
            > 0
        )
    async with resources() as (saver, store):
        await process_run(
            run,
            "test-worker",
            saver,
            store,
            FakeModel(
                [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "private-review",
                                "name": "propose_action",
                                "args": {
                                    "action": "tasks.create",
                                    "payload": {"items": [{"title": "Private pending task"}]},
                                },
                            }
                        ],
                    }
                ]
            ),
        )
        assert await saver.aget_tuple({"configurable": {"thread_id": thread["id"]}})
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["proposals"] and history["messages"] and history["runs"]
    deleted = client.delete(f"/projects/{project['id']}?version={project['version']}")
    assert deleted.status_code == 200, deleted.text
    assert not original.exists()
    assert client.get(f"/conversations/{thread['id']}").status_code == 404
    assert client.get(f"/runs/{run.id}").status_code == 404
    assert client.get(f"/documents/{document_id}/preview").status_code == 404
    assert [item["id"] for item in client.get("/notes").json()] == [personal_note["id"]]
    assert [item["id"] for item in client.get("/memories").json()] == [personal_memory["id"]]
    with transaction() as db:
        counts = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in (
                Project,
                Conversation,
                Document,
                Chunk,
                IngestionJob,
                Message,
                Run,
                RunEvent,
                Proposal,
                Task,
            )
        }
        counts.update(
            {
                table: db.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE thread_id=:thread"),
                    {"thread": thread["id"]},
                )
                for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
            }
        )
        assert all(count == 0 for count in counts.values()), counts
    # Individual deletion paths must also remove their canonical records.
    assert (
        client.delete(
            f"/notes/{personal_note['id']}?version={personal_note['version']}"
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/memories/{personal_memory['id']}?version={personal_memory['version']}"
        ).status_code
        == 200
    )
    for kind in ("tasks", "conversations"):
        item = client.post(f"/{kind}", json={"title": "Individual deletion"}).json()
        assert client.delete(f"/{kind}/{item['id']}?version={item['version']}").status_code == 200
        assert client.get(f"/{kind}/{item['id']}").status_code == 404
    direct_doc = client.post(
        "/documents", files={"file": ("direct.txt", b"Direct delete original", "text/plain")}
    ).json()
    with transaction() as db:
        direct_original = settings.blobs / db.get(Document, direct_doc["id"]).blob
    assert (
        client.delete(f"/documents/{direct_doc['id']}?version={direct_doc['version']}").status_code
        == 200
    )
    assert not direct_original.exists()
    assert client.get("/memories").json() == []
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(Note)) == 0
        assert db.scalar(select(func.count()).select_from(IngestionJob)) == 0
    root = Path(__file__).resolve().parents[3]
    (root / "artifacts/prepublication/DAT-04-deletion-audit.json").write_text(
        json.dumps(
            {
                "project_cascade_counts": counts,
                "original_removed": True,
                "personal_controls_preserved": True,
                "individual_paths_deleted": [
                    "notes",
                    "memories",
                    "tasks",
                    "conversations",
                    "documents",
                ],
                "scope": "Disposable nexus_test; real API/SQL/store/checkpoints/file persistence, deterministic provider only. Account/session and metadata-only audit records are deliberately retained; no account-erasure feature is claimed.",
            },
            indent=2,
        )
    )
