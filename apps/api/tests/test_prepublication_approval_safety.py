from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from nexus import actions
from nexus.actions import execute, propose
from nexus.db import transaction
from nexus.models import Proposal, Run
from sqlalchemy import select
from test_graph import setup_run


def waiting(db_run):
    with transaction() as db:
        db.get(Run, db_run.id).status = "waiting"


def test_project_id_cannot_change_in_decision(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    projects = [client.post("/projects", json={"title": f"Scope {i}"}).json() for i in range(2)]
    proposal = propose(
        user["id"],
        thread["id"],
        run.id,
        "scope",
        "tasks.create",
        {"items": [{"title": "Scoped task", "project_id": projects[0]["id"]}]},
    )
    waiting(run)
    edited = deepcopy(proposal["payload"])
    edited["items"][0]["project_id"] = projects[1]["id"]
    response = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"approve": True, "version": 1, "payload": edited},
    )
    assert response.status_code == 422 and "project" in response.text
    assert client.get("/tasks").json() == []


def test_seven_day_expiry_boundary(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    clock = datetime(2026, 10, 25, tzinfo=UTC)
    monkeypatch.setattr(actions, "now", lambda: clock)
    proposal = propose(
        user["id"],
        thread["id"],
        run.id,
        "expiry",
        "tasks.create",
        {"items": [{"title": "Expires"}]},
    )
    with transaction() as db:
        assert db.get(Proposal, proposal["id"]).expires_at == clock + timedelta(days=7)
    waiting(run)
    monkeypatch.setattr(actions, "now", lambda: clock + timedelta(days=7))
    assert (
        client.post(
            f"/proposals/{proposal['id']}/decision", json={"approve": True, "version": 1}
        ).status_code
        == 409
    )
    assert client.get("/tasks").json() == []


@pytest.mark.asyncio
async def test_replaying_same_decision_returns_known_outcome(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    proposal = propose(
        user["id"], thread["id"], run.id, "replay", "tasks.create", {"items": [{"title": "Once"}]}
    )
    waiting(run)
    request = {"approve": True, "version": 1, "payload": proposal["payload"]}
    first = client.post(f"/proposals/{proposal['id']}/decision", json=request)
    assert first.status_code == 200
    repeated = client.post(f"/proposals/{proposal['id']}/decision", json=request)
    assert repeated.status_code == 200 and repeated.json()["already_decided"] is True
    outcome = await execute(None, user["id"], proposal["id"])
    repeated = client.post(f"/proposals/{proposal['id']}/decision", json=request)
    assert repeated.status_code == 200 and repeated.json()["outcome"] == outcome
    assert len(client.get("/tasks").json()) == 1
    changed = deepcopy(request)
    changed["payload"]["items"][0]["title"] = "Unapproved replacement"
    assert client.post(f"/proposals/{proposal['id']}/decision", json=changed).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tasks", "notes", "memories"])
async def test_fourth_write_failure_rolls_back_whole_batch(client, monkeypatch, kind):
    user, thread, run = setup_run(client, monkeypatch)
    payload = {
        "items": [
            {"title": f"Atomic {i}"} | ({"content": "Atomic content"} if kind != "tasks" else {})
            for i in range(5)
        ]
    }
    proposal = propose(user["id"], thread["id"], run.id, "atomic", f"{kind}.create", payload)
    waiting(run)
    assert (
        client.post(
            f"/proposals/{proposal['id']}/decision", json={"approve": True, "version": 1}
        ).status_code
        == 200
    )
    calls = 0
    if kind == "memories":
        original = actions.save_memory

        async def fail_fourth(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise HTTPException(409, "Synthetic fourth-write failure")
            return await original(*args, **kwargs)

        monkeypatch.setattr(actions, "save_memory", fail_fourth)
    else:
        original = actions.save

        def fail_fourth(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise HTTPException(409, "Synthetic fourth-write failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(actions, "save", fail_fourth)
    with pytest.raises(HTTPException):
        await execute(None, user["id"], proposal["id"])
    assert calls == 4 and client.get("/" + kind).json() == []
    with transaction() as db:
        persisted = db.scalar(select(Proposal).where(Proposal.id == proposal["id"]))
        assert persisted.outcome is None and persisted.status == "approved"
    monkeypatch.setattr(actions, "save_memory" if kind == "memories" else "save", original)
    assert len((await execute(None, user["id"], proposal["id"]))["saved"]) == 5
    assert len(client.get("/" + kind).json()) == 5
