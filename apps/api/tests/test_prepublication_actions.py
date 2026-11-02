"""Approve/reject/edit/failure matrix for all nine real transactional action types."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from nexus.actions import execute, propose
from nexus.db import transaction
from nexus.models import AuditEvent, Run
from sqlalchemy import select
from test_graph import setup_run


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tasks", "notes", "memories"])
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("decision", ["approve", "reject", "edit", "failure"])
async def test_all_action_decision_paths(client, monkeypatch, kind, operation, decision):
    user, thread, run = setup_run(client, monkeypatch)
    project = client.post("/projects", json={"title": "Action scope"}).json()
    original = None
    if operation != "create":
        original = client.post(
            "/" + kind,
            json={"title": "Original", "project_id": project["id"]}
            | ({"content": "Original content"} if kind != "tasks" else {}),
        ).json()
    item = {"title": "Proposed", "project_id": project["id"]}
    if kind == "tasks":
        item |= {
            "description": "Task details",
            "status": "in_progress",
            "priority": "high",
            "due_date": "2026-11-01",
        }
    else:
        item["content"] = "**Markdown**\n\n| Stage | Owner |\n| - | - |\n| Review | Lina |"
        if kind == "memories":
            item |= {"category": "project_decision", "enabled": False}
    if original:
        item |= {"id": original["id"], "version": original["version"]}
    proposal = propose(
        user["id"], thread["id"], run.id, "matrix-call", f"{kind}.{operation}", {"items": [item]}
    )
    assert len(client.get("/" + kind).json()) == (1 if original else 0)
    with transaction() as db:
        db.get(Run, run.id).status = "waiting"
    edited = deepcopy(proposal["payload"])
    if decision == "failure":
        if operation == "create":
            edited["items"][0]["title"] = ""
        else:
            changed = client.put(
                f"/{kind}/{original['id']}",
                json={
                    "title": "Changed manually",
                    "version": original["version"],
                    "project_id": project["id"],
                }
                | ({"content": "Changed manually"} if kind != "tasks" else {}),
            )
            assert changed.status_code == 200
    elif decision == "edit":
        if operation == "delete":
            edited["items"][0]["include"] = False
        else:
            edited["items"][0]["title"] = "Edited by reviewer"
            if kind != "tasks":
                edited["items"][0]["content"] = "**Edited** content"
    response = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"approve": decision != "reject", "version": proposal["version"], "payload": edited},
    )
    if decision == "failure":
        if operation == "create":
            assert response.status_code == 422, response.text
        elif kind == "memories":
            assert response.status_code == 200
            with pytest.raises(HTTPException) as error:
                await execute(None, user["id"], proposal["id"])
            assert error.value.status_code == 409
        else:
            assert response.status_code == 409
        saved = client.get("/" + kind).json()
        assert len(saved) == (1 if original else 0)
        if original:
            assert saved[0]["title"] == "Changed manually"
        return
    assert response.status_code == 200, response.text
    outcome = await execute(None, user["id"], proposal["id"])
    assert await execute(None, user["id"], proposal["id"]) == outcome
    saved = client.get("/" + kind).json()
    if decision == "reject" or (decision == "edit" and operation == "delete"):
        assert not outcome["saved"]
        assert len(saved) == (1 if original else 0)
        if original:
            assert saved[0]["title"] == "Original"
    elif operation == "delete":
        assert saved == [] and outcome["saved"][0]["deleted"]
    else:
        assert len(saved) == 1
        assert saved[0]["title"] == ("Edited by reviewer" if decision == "edit" else "Proposed")
        assert saved[0]["project_id"] == project["id"]
        assert saved[0]["version"] == (2 if original else 1)
        if kind == "tasks":
            assert saved[0]["status"] == "in_progress" and saved[0]["priority"] == "high"
            assert (
                saved[0]["due_date"] == "2026-11-01" and saved[0]["description"] == "Task details"
            )
        else:
            assert saved[0]["content"] == (
                "**Edited** content" if decision == "edit" else item["content"]
            )
            if kind == "memories":
                assert saved[0]["category"] == "project_decision" and saved[0]["enabled"] is False
    with transaction() as db:
        events = list(
            db.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == proposal["id"]))
        )
        assert events.count("proposal.decision") == 1
        if decision != "reject":
            assert events.count("proposal.executed") == 1
