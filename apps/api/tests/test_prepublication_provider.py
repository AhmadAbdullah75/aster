"""Provider failure boundaries use dummy responses, never the owner's API quota."""

import pytest
from google.genai.errors import ClientError
from langchain_core.messages import AIMessageChunk
from nexus.graph_resources import resources
from nexus.worker import process_run
from test_graph import setup_run


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["no_chunks", "empty", "whitespace", "malformed"])
async def test_empty_or_malformed_provider_response_fails_once(client, monkeypatch, scenario):
    _, thread, run = setup_run(client, monkeypatch)

    class Provider:
        calls = 0

        def bind_tools(self, *args, **kwargs):
            return self

        async def astream(self, messages):
            self.calls += 1
            if scenario == "no_chunks":
                return
            if scenario == "malformed":
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": "calculator", "args": "{broken", "id": "bad", "index": 0}
                    ],
                )
            else:
                yield AIMessageChunk(content="  \n" if scenario == "whitespace" else "")

    model = Provider()
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][0]["status"] == "failed"
    assert "Provider returned" in history["runs"][0]["error"]
    assert model.calls == 1
    assert client.get("/tasks").json() == []


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 503])
def test_google_errors_hide_raw_key_and_request(code):
    from nexus.agent import safe_error

    secret = "synthetic-secret-key-never-a-real-key"
    text = safe_error(ClientError(code, {"error": {"message": secret + " private request"}}))
    assert secret not in text and "private request" not in text
    assert f"HTTP {code}" in text
    assert "No paid fallback" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["blocked", "empty", "extra_results"])
async def test_free_search_failure_and_hard_five_result_limit(monkeypatch, failure):
    from nexus import provider
    from nexus.config import settings

    monkeypatch.setattr(settings, "web_backend", "ddgs")

    class Search:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 12

        def text(self, query, **kwargs):
            assert kwargs == {"max_results": 5, "backend": "duckduckgo"}
            if failure == "blocked":
                raise RuntimeError("Synthetic blocked network")
            return (
                []
                if failure == "empty"
                else [{"href": f"https://example.com/{i}", "body": "Evidence"} for i in range(8)]
            )

    monkeypatch.setattr(provider, "DDGS", Search)
    if failure == "extra_results":
        assert len((await provider.web_search("Synthetic question"))["sources"]) == 5
    else:
        with pytest.raises(ValueError, match="unavailable|no sources"):
            await provider.web_search("Synthetic question")


def test_indicator_is_configuration_only_and_sdk_budget_is_4096(client, monkeypatch):
    from conftest import register
    from nexus import provider
    from nexus.config import settings

    register(client)
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "free_only", True)
    monkeypatch.setattr(settings, "gemini_api_key", "synthetic-invalid-key")
    assert client.get("/capabilities").json()["chat"] is True
    captured = {}

    def model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(provider, "ChatGoogleGenerativeAI", model)
    provider.chat_model()
    assert captured["max_tokens"] == 4096
    assert captured["retries"] == 2
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert client.get("/capabilities").json()["chat"] is False
    assert client.post("/notes", json={"title": "Works without a key"}).status_code == 200
    assert client.post("/tasks", json={"title": "Works without a key"}).status_code == 200
    assert (
        client.post(
            "/memories", json={"title": "Manual memory", "content": "Works without a key"}
        ).status_code
        == 200
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["MAX_TOKENS", "length"])
async def test_output_limit_preserves_partial_and_does_not_retry(client, monkeypatch, reason):
    from test_graph import FakeModel

    _, thread, run = setup_run(client, monkeypatch)
    model = FakeModel(
        [
            {
                "content": "Saved partial response. " * 1500,
                "response_metadata": {"finish_reason": reason},
            }
        ]
    )
    async with resources() as (saver, store):
        await process_run(run, "test-worker", saver, store, model)
    history = client.get(f"/conversations/{thread['id']}/history").json()
    assert history["runs"][0]["status"] == "failed"
    assert "output limit" in history["runs"][0]["error"]
    assert history["messages"][1]["content"] == "Saved partial response. " * 1500
    assert history["messages"][1]["interrupted"] is True
    assert len(model.prompts) == 1
