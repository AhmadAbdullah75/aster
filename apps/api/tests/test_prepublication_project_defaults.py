import pytest
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Conversation, Message, Run
from nexus.worker import claim_run, process_run
from sqlalchemy import select
from test_graph import FakeModel, setup_run


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["tasks", "notes"])
@pytest.mark.parametrize("personal", [False, True])
async def test_project_create_defaults_are_reviewed_saved_and_cascade_with_project(
    client, monkeypatch, kind, personal
):
    _, thread, run = setup_run(client, monkeypatch)
    project = client.post("/projects", json={"title": "Default project"}).json()
    with transaction() as db:
        db.get(Conversation, thread["id"]).project_id = project["id"]
        query = (
            f"Propose two personal {kind}." if personal else f"Propose two {kind} for this project."
        )
        db.get(Run, run.id).input = {"message": query}
        db.scalar(select(Message).where(Message.run_id == run.id)).content = query
        run.input = {"message": query}
    items = [{"title": "Omitted scope"}, {"title": "Null scope", "project_id": None}]
    if kind == "notes":
        for item in items:
            item["content"] = "Synthetic project note."
    model = FakeModel(
        [
            {
                "tool_calls": [
                    {
                        "id": "project-default",
                        "name": "propose_action",
                        "args": {"action": kind + ".create", "payload": {"items": items}},
                    }
                ],
                "content": "",
            }
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][-1]["status"] == "waiting", history["runs"][-1]
    proposal = history["proposals"][0]
    expected_project = None if personal else project["id"]
    assert {item["project_id"] for item in proposal["payload"]["items"]} == {expected_project}
    assert client.get("/" + kind).json() == []
    result = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"approve": True, "version": proposal["version"]},
    )
    assert result.status_code == 200
    async with resources() as (saver, store):
        await process_run(
            claim_run("test-worker"),
            "test-worker",
            saver,
            store,
            FakeModel([{"content": "Saved the reviewed project items."}]),
        )
    saved = client.get("/" + kind).json()
    assert len(saved) == 2 and {item["project_id"] for item in saved} == {expected_project}
    assert (
        client.delete(f"/projects/{project['id']}?version={project['version']}").status_code == 200
    )
    remaining = client.get("/" + kind).json()
    assert len(remaining) == (2 if personal else 0)
