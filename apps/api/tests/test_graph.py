import pytest
from conftest import register
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from nexus.actions import decide, execute, propose
from nexus.agent import build_graph
from nexus.config import settings
from nexus.db import transaction
from nexus.graph_resources import resources
from nexus.memory import list_memories, relevant_memories
from nexus.models import Message, Run
from nexus.schemas import Decision
from nexus.worker import claim_run, process_run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrapped_citation, explanation_fails", [(False, False), (True, False), (False, True)]
)
async def test_document_explanation_is_cited_before_pending_approval(
    client, monkeypatch, wrapped_citation, explanation_fails
):
    from nexus import documents
    from nexus.models import Chunk, Document
    from sqlalchemy import select

    user, thread, run = setup_run(client, monkeypatch)

    async def embedding(texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]

    monkeypatch.setattr(documents, "embed", embedding)
    with transaction() as db:
        doc = Document(
            user_id=user["id"],
            filename="Audit evidence.md",
            blob="test-only.md",
            sha256=run.id,
            size=40,
            media_type="text/markdown",
            status="ready",
            embedding_model=settings.embedding_model,
            embedding_dimensions=1536,
        )
        db.add(doc)
        db.flush()
        chunk = Chunk(
            user_id=user["id"],
            document_id=doc.id,
            position=0,
            section="Discovery",
            content="Discovery confirms scope before launch.",
            embedding=(await embedding([""]))[0],
        )
        db.add(chunk)
        db.flush()
        source_id = chunk.id
        run.input = {
            "message": "Explain this proposal and propose a task.",
            "mode": "documents",
            "document_ids": [doc.id],
        }
        db.get(Run, run.id).input = run.input
        db.scalar(select(Message).where(Message.run_id == run.id)).content = run.input["message"]

    class ExplainingModel(FakeModel):
        explanation_calls = 0

        async def ainvoke(self, messages):
            self.explanation_calls += 1
            if explanation_fails:
                raise RuntimeError("Synthetic explanation provider outage")
            return AIMessage(
                content=[
                    {
                        "type": "text",
                        "text": f"Discovery confirms scope before launch. [source:{source_id}]",
                    }
                ]
            )

    model = ExplainingModel(
        [
            {
                "content": f"Discovery confirms scope before launch. [Source:{{{source_id.upper()}}}]"
                if wrapped_citation
                else "",
                "tool_calls": [
                    {
                        "id": "proposed-task",
                        "name": "propose_action",
                        "args": {
                            "action": "tasks.create",
                            "payload": {"items": [{"title": "Confirm scope"}]},
                        },
                    }
                ],
            },
            {"content": "The approved task was saved."},
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    if explanation_fails:
        assert history["runs"][0]["status"] == "failed"
        assert history["proposals"][0]["status"] == "stale"
        assert client.get("/tasks").json() == []
        return
    assert history["runs"][0]["status"] == "waiting", history["runs"][0]["error"]
    assert f"[source:{source_id}]" in history["messages"][-1]["content"]
    assert "Discovery confirms scope" in history["messages"][-1]["content"]
    assert model.explanation_calls == (0 if wrapped_citation else 1)
    assert client.get("/sources/" + source_id).status_code == 200
    assert client.get("/tasks").json() == []
    proposal = history["proposals"][0]
    assert (
        client.post(
            f"/proposals/{proposal['id']}/decision",
            json={"approve": True, "version": proposal["version"]},
        ).status_code
        == 200
    )
    async with resources() as (saver, store):
        await process_run(claim_run("test-worker"), "test-worker", saver, store, model)
    assert len(client.get("/tasks").json()) == 1
    tool_results = [
        message
        for message in model.prompts[-1]
        if isinstance(message, ToolMessage) and message.tool_call_id == "proposed-task"
    ]
    assert len(tool_results) == 1 and "Canceled before completion" not in tool_results[0].content


class FakeModel:
    """Test-only provider. Real StateGraph, Postgres checkpoints/store/services remain in use."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def bind_tools(self, *args, **kwargs):
        return self

    async def astream(self, messages):
        self.prompts.append(messages)
        response = self.responses.pop(0)
        yield AIMessageChunk(**response)


def setup_run(client, monkeypatch):
    user = register(client)
    thread = client.post("/conversations", json={}).json()
    monkeypatch.setattr(settings, "openai_api_key", "test-only-not-a-provider-key")
    response = client.post(
        f"/conversations/{thread['id']}/runs", json={"message": "Help me organize my work."}
    )
    assert response.status_code == 202, response.text
    return user, thread, claim_run("test-worker")


@pytest.mark.asyncio
async def test_durable_chat_reopen_and_thread_isolation(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    async with resources() as (saver, store):
        model = FakeModel(
            [
                {
                    "content": "A streaming response with enough characters to persist before final completion. Hello Alice."
                }
            ]
        )
        await process_run(run, "test-worker", saver, store, model)
    assert client.get("/runs/" + run.id).json()["status"] == "completed"
    events = client.get("/runs/" + run.id + "/events").text
    assert "message.delta" in events and "run.completed" in events
    async with resources() as (saver, store):
        snapshot = await build_graph(saver, store).aget_state(
            {"configurable": {"thread_id": thread["id"]}}
        )
        assert len(snapshot.values["messages"]) == 2
        empty = await build_graph(saver, store).aget_state(
            {"configurable": {"thread_id": "unrelated"}}
        )
        assert not empty.values
    # Reopening new resources above creates fresh connections, as after restart.
    assert len(client.get("/conversations/" + thread["id"] + "/history").json()["messages"]) == 2
    assert "message.delta" not in client.get("/runs/" + run.id + "/events?cursor=999").text
    assert client.post("/auth/logout").status_code == 200
    register(client, "bob@example.com")
    for route in [
        f"/runs/{run.id}",
        f"/runs/{run.id}/events",
        f"/conversations/{thread['id']}/history",
    ]:
        assert client.get(route).status_code == 404


@pytest.mark.asyncio
async def test_interrupt_edit_resume_exactly_once_and_reject(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    model = FakeModel(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "propose_action",
                        "id": "call-write",
                        "args": {
                            "action": "tasks.create",
                            "payload": {
                                "items": [{"title": "Original milestone", "due_date": "2030-01-01"}]
                            },
                        },
                    }
                ],
            },
            {"content": "Your approved task was saved."},
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    assert client.get("/runs/" + run.id).json()["status"] == "waiting"
    assert client.get("/tasks").json() == []
    proposal = client.get("/conversations/" + thread["id"] + "/history").json()["proposals"][0]
    items = proposal["payload"]["items"]
    items[0]["title"] = "Edited milestone"
    response = client.post(
        "/proposals/" + proposal["id"] + "/decision",
        json={"approve": True, "version": 1, "payload": {"items": items}},
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            "/proposals/" + proposal["id"] + "/decision", json={"approve": True, "version": 1}
        ).status_code
        == 409
    )
    resumed = claim_run("test-worker")
    async with resources() as (saver, store):
        # Simulate write committed before checkpoint, followed by replay in the real graph.
        outcome = await execute(store, user["id"], proposal["id"])
        assert outcome["status"] == "completed"
        await process_run(resumed, "test-worker", saver, store, model)
        assert await execute(store, user["id"], proposal["id"]) == outcome
    tasks = client.get("/tasks").json()
    assert len(tasks) == 1 and tasks[0]["title"] == "Edited milestone"
    assert client.get("/runs/" + run.id).json()["status"] == "completed"
    # Every model tool call gets a matching result on resume.
    assert any(
        isinstance(m, ToolMessage) and m.tool_call_id == "call-write" for m in model.prompts[-1]
    )


@pytest.mark.asyncio
async def test_memory_approval_cross_thread_controls_and_rejection(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    proposal = propose(
        user["id"],
        thread["id"],
        run.id,
        "memory-call",
        "memories.create",
        {
            "items": [
                {
                    "title": "Writing preference",
                    "content": "I prefer simple English",
                    "category": "preference",
                }
            ]
        },
    )
    with transaction() as db:
        db.get(Run, run.id).status = "waiting"
    decide(user["id"], proposal["id"], Decision(approve=True, version=1))
    async with resources() as (saver, store):
        await execute(store, user["id"], proposal["id"])
        await execute(store, user["id"], proposal["id"])
        memories = await list_memories(store, user["id"])
        assert len(memories) == 1 and "simple English" in memories[0]["content"]
        assert await relevant_memories(store, user["id"], "Write for me", None)
        assert not await relevant_memories(store, "another-user", "Write", None)
    memory = client.get("/memories").json()[0]
    value = {
        k: memory[k] for k in ["title", "content", "category", "enabled", "project_id", "version"]
    }
    value["enabled"] = False
    assert client.put("/memories/" + memory["id"], json=value).status_code == 200
    async with resources() as (saver, store):
        assert not await relevant_memories(store, user["id"], "Write", None)
    assert client.delete(f"/memories/{memory['id']}?version=2").status_code == 200
    assert client.get("/memories").json() == []


@pytest.mark.asyncio
async def test_reject_keeps_task_state_unchanged(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    model = FakeModel(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "propose_action",
                        "id": "reject-call",
                        "args": {
                            "action": "tasks.create",
                            "payload": {"items": [{"title": "Must not save"}]},
                        },
                    }
                ],
            },
            {"content": "Rejected. No tasks were saved."},
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
        proposal = client.get("/conversations/" + thread["id"] + "/history").json()["proposals"][0]
        assert (
            client.post(
                "/proposals/" + proposal["id"] + "/decision", json={"approve": False, "version": 1}
            ).status_code
            == 200
        )
        await process_run(claim_run("test-worker"), "test-worker", saver, store, model)
    assert client.get("/tasks").json() == []


@pytest.mark.asyncio
async def test_natural_task_request_cannot_end_with_only_text_proposal(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    run.input = {"message": "Propose a task for my launch"}
    model = FakeModel(
        [
            {"content": "Here is a proposed task: confirm scope."},
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "natural-action",
                        "name": "propose_action",
                        "args": {
                            "action": "tasks.create",
                            "payload": {"items": [{"title": "Confirm scope"}]},
                        },
                    }
                ],
            },
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    assert client.get("/runs/" + run.id).json()["status"] == "waiting"
    assert len(client.get("/conversations/" + thread["id"] + "/history").json()["proposals"]) == 1
    assert client.get("/tasks").json() == []


@pytest.mark.asyncio
async def test_real_graph_summary_prunes_context_and_preserves_transcript(client, monkeypatch):
    user, thread, run = setup_run(client, monkeypatch)
    monkeypatch.setattr(settings, "context_tokens", 4500)
    previous = []
    for index in range(6):
        previous.extend(
            [
                HumanMessage(
                    content="Remember the Friday deadline. " + "background " * 600,
                    id=f"old-human-{index}",
                ),
                AIMessage(content="Acknowledged. " + "details " * 600, id=f"old-ai-{index}"),
            ]
        )
    with transaction() as db:
        for message in previous:
            db.add(
                Message(
                    user_id=user["id"],
                    conversation_id=thread["id"],
                    role="user" if message.type == "human" else "assistant",
                    content=str(message.content),
                )
            )

    class SummaryModel(FakeModel):
        async def ainvoke(self, messages):
            return AIMessage(content="Key constraint: preserve the Friday deadline.")

    model = SummaryModel([{"content": "The Friday deadline remains in scope."}])
    async with resources() as (saver, store):
        graph = build_graph(saver, store)
        await graph.aupdate_state(
            {"configurable": {"thread_id": thread["id"]}}, {"messages": previous}
        )
        await process_run(run, "test-worker", saver, store, model)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread["id"]}})
        assert "Friday" in snapshot.values["summary"]
        assert len(snapshot.values["messages"]) == 2
    assert "Friday" in model.prompts[0][0].content
    assert len(client.get("/conversations/" + thread["id"] + "/history").json()["messages"]) == 14
