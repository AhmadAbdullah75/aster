from datetime import UTC, datetime

import pytest
from nexus import tools
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.models import Message, Run
from nexus.tools import requested_weekday_date
from nexus.worker import claim_run, process_run
from sqlalchemy import select
from test_graph import FakeModel, setup_run


@pytest.mark.parametrize(
    "query,timezone,current,expected",
    [
        (
            "Create one task due next Friday",
            "Asia/Karachi",
            "2026-10-25T07:00:00+00:00",
            "2026-10-30",
        ),
        ("next Friday", "UTC", "2026-10-30T07:00:00+00:00", "2026-11-06"),
        ("next Friday", "UTC", "2026-12-31T07:00:00+00:00", "2027-01-01"),
        ("next Friday", "UTC", "2026-10-29T23:30:00+00:00", "2026-10-30"),
        ("next Friday", "Pacific/Auckland", "2026-10-29T23:30:00+00:00", "2026-11-06"),
        ("next Friday and next Monday", "UTC", "2026-10-25T07:00:00+00:00", None),
        ("next Friday November 6", "UTC", "2026-10-25T07:00:00+00:00", None),
        ("the task mentions Friday", "UTC", "2026-10-25T07:00:00+00:00", None),
    ],
)
def test_next_weekday_calendar_boundaries(query, timezone, current, expected):
    assert requested_weekday_date(query, timezone, datetime.fromisoformat(current)) == expected


@pytest.mark.asyncio
async def test_single_task_relative_draft_corrects_model_date_but_preserves_review_edit(
    client, monkeypatch
):
    user, thread, run = setup_run(client, monkeypatch)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 25, 7, tzinfo=UTC).astimezone(tz or UTC)

    monkeypatch.setattr(tools, "datetime", Clock)
    query = "Create one task due next Friday. Use the current clock."
    run.input = {"message": query}
    with transaction() as db:
        db.get(Run, run.id).input = {"message": query}
        db.scalar(select(Message).where(Message.run_id == run.id)).content = query
    model = FakeModel(
        [
            {
                "content": "",
                "tool_calls": [{"id": "clock", "name": "current_datetime", "args": {}}],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "draft",
                        "name": "propose_action",
                        "args": {
                            "action": "tasks.create",
                            "payload": {
                                "items": [{"title": "Friday check", "due_date": "2026-11-06"}]
                            },
                        },
                    }
                ],
            },
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][0]["status"] == "waiting", history["runs"][0]["error"]
    proposal = history["proposals"][0]
    assert proposal["payload"]["items"][0]["due_date"] == "2026-10-30"
    assert client.get("/tasks").json() == []
    edited = proposal["payload"]
    edited["items"][0]["due_date"] = "2026-10-31"
    response = client.post(
        f"/proposals/{proposal['id']}/decision",
        json={"approve": True, "version": proposal["version"], "payload": edited},
    )
    assert response.status_code == 200
    async with resources() as (saver, store):
        await process_run(
            claim_run("test-worker"),
            "test-worker",
            saver,
            store,
            FakeModel([{"content": "Your reviewed task was saved."}]),
        )
    tasks = client.get("/tasks").json()
    assert len(tasks) == 1 and tasks[0]["due_date"] == "2026-10-31"
