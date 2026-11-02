from datetime import UTC, datetime

import pytest
from langchain_core.messages import ToolMessage
from nexus import tools
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Message, Run
from nexus.worker import claim_run, process_run
from sqlalchemy import select
from test_graph import FakeModel, setup_run


@pytest.fixture
def local_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 26, 20, tzinfo=UTC).astimezone(tz or UTC)

    monkeypatch.setattr(tools, "datetime", Clock)


@pytest.mark.parametrize(
    "query,timezone,end",
    [
        ("Tasks within the next fourteen local calendar days", "Asia/Karachi", "2026-11-10"),
        ("make a 2-week plan as tasks", "Asia/Karachi", "2026-11-10"),
        ("a two week plan", "UTC", "2026-11-09"),
        ("plan my next two weeks", "UTC", "2026-11-09"),
        ("a plan with no horizon", "UTC", None),
        ("next 0 days", "UTC", None),
    ],
)
def test_local_planning_window(local_clock, query, timezone, end):
    window = tools.requested_planning_window(query, timezone)
    assert (window[1].isoformat() if window else None) == end


def draft(call, items):
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call,
                "name": "propose_action",
                "args": {"action": "tasks.create", "payload": {"items": items}},
            }
        ],
    }


@pytest.mark.asyncio
async def test_plan_rejects_later_source_deadlines_preserves_review_and_blocks_reproposal(
    client, monkeypatch, local_clock
):
    _, thread, run = setup_run(client, monkeypatch)
    query = "Propose tasks with due dates within the next fourteen local calendar days."
    run.input = {"message": query}
    with transaction() as db:
        db.get(Run, run.id).input = run.input
        db.scalar(select(Message).where(Message.run_id == run.id)).content = query
    valid = [
        {"title": "First", "due_date": "2026-11-02"},
        {"title": "Excluded", "due_date": "2026-11-10"},
    ]
    model = FakeModel(
        [
            draft("bad", [{"title": "Later source milestone", "due_date": "2026-11-12"}]),
            draft("good", valid),
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][-1]["status"] == "waiting", history["runs"][-1]
    assert len(history["proposals"]) == 1
    assert any(isinstance(m, ToolMessage) and "2026-11-10" in m.content for m in model.prompts[-1])
    proposal = history["proposals"][0]
    edited = proposal["payload"]
    edited["items"][0]["due_date"] = "2026-11-20"  # Explicit human edits remain authoritative.
    edited["items"][1]["include"] = False
    decision = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"approve": True, "version": proposal["version"], "payload": edited},
    )
    assert decision.status_code == 200, decision.text
    continuation = FakeModel(
        [
            draft("unwanted", [{"title": "Excluded again"}]),
            {"content": "Saved only your reviewed selection."},
        ]
    )
    async with resources() as (saver, store):
        await process_run(claim_run("test-worker"), "test-worker", saver, store, continuation)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][-1]["status"] == "completed", history["runs"][-1]
    assert len(history["proposals"]) == 1
    tasks = client.get("/tasks").json()
    assert len(tasks) == 1 and tasks[0]["due_date"] == "2026-11-20"
    assert (
        client.post(
            f"/conversations/{thread['id']}/runs", json={"message": "Propose another task."}
        ).status_code
        == 202
    )
    async with resources() as (saver, store):
        await process_run(
            claim_run("test-worker"),
            "test-worker",
            saver,
            store,
            FakeModel([draft("new-turn", [{"title": "Newly requested"}])]),
        )
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][-1]["status"] == "waiting"
    assert len(history["proposals"]) == 2
