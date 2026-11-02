"""Live harness safety uses dummy credentials/temporary ledgers, never real quota."""

import logging
import os
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_pacing_allowance_is_scoped_and_restored_even_on_failure(helper, monkeypatch):
    local_settings = SimpleNamespace(
        run_timeout_seconds=180, max_tool_calls=12, request_timeout_seconds=60
    )
    monkeypatch.setitem(helper, "settings", local_settings)
    assert local_settings.run_timeout_seconds == 180
    with pytest.raises(RuntimeError, match="controlled failure"):
        async with helper["paced_run_timeout"]() as scope:
            assert scope["production_timeout_seconds"] == 180
            assert local_settings.run_timeout_seconds > 180
            assert local_settings.request_timeout_seconds == 60
            assert local_settings.max_tool_calls == 12
            raise RuntimeError("controlled failure")
    assert local_settings.run_timeout_seconds == 180
    assert local_settings.request_timeout_seconds == 60


@pytest.fixture
def helper(tmp_path, monkeypatch):
    (tmp_path / "apps/api/nexus").mkdir(parents=True)
    (tmp_path / "artifacts/prepublication").mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://unused:unused@127.0.0.1/unused\n"
        "GEMINI_API_KEY=synthetic-no-provider-access\n"
    )
    (tmp_path / "artifacts/prepublication/results.json").write_text("{}")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("NEXUS_LIVE_PREPUBLICATION", "true")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT / "apps/api"))
    loaded = runpy.run_path(str(ROOT / "tests/e2e/live_flow_worker.py"), run_name="live_flow_unit")
    return loaded["main"].__globals__


def test_quota_log_stops_before_a_second_request_without_touching_real_ledger(helper, monkeypatch):
    observations = []
    monkeypatch.setitem(helper, "halt_quota", lambda: observations.append("halted"))

    def exit_only_this_mock(code):
        observations.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(os, "_exit", exit_only_this_mock)
    handler = helper["QuotaStop"]()
    handler.emit(logging.LogRecord("httpx", logging.INFO, "", 0, "HTTP/1.1 200 OK", (), None))
    assert observations == []
    with pytest.raises(SystemExit) as stopped:
        handler.emit(
            logging.LogRecord(
                "httpx", logging.INFO, "", 0, "HTTP/1.1 429 RESOURCE_EXHAUSTED", (), None
            )
        )
    assert stopped.value.code == 75
    assert observations == ["halted", 75]


@pytest.mark.asyncio
async def test_embedding_client_uses_one_attempt_and_paces_before_network(helper, monkeypatch):
    calls = []

    async def gate():
        calls.append("paced")

    class Connection:
        async def __aenter__(self):
            return "dummy-local-connection"

        async def __aexit__(self, *args):
            return False

    def client(**kwargs):
        calls.append("constructed")
        assert kwargs["api_key"] == "synthetic-no-provider-access"
        assert kwargs["http_options"].retry_options.attempts == 1
        assert kwargs["vertexai"] is False
        return SimpleNamespace(aio=Connection())

    monkeypatch.setitem(helper, "gate", gate)
    monkeypatch.setattr(helper["settings"], "gemini_api_key", "synthetic-no-provider-access")
    monkeypatch.setattr(helper["provider"], "require_provider", lambda: None)
    monkeypatch.setattr(helper["genai"], "Client", client)
    async with helper["single_attempt_google_client"]() as connection:
        assert connection == "dummy-local-connection"
    assert calls == ["paced", "constructed"]


@pytest.mark.asyncio
async def test_paced_bound_model_keeps_actual_stream_and_response(helper, monkeypatch):
    calls = []

    async def gate():
        calls.append("paced")

    class Actual:
        def bind_tools(self, tools, **kwargs):
            calls.append((tools, kwargs))
            return self

        async def ainvoke(self, messages):
            calls.append(messages)
            return "local-result"

        async def astream(self, messages):
            calls.append(messages)
            yield "local-chunk"

    monkeypatch.setitem(helper, "gate", gate)
    model = helper["PacedModel"](Actual()).bind_tools(["tool"], tool_choice="propose_action")
    assert await model.ainvoke(["one"]) == "local-result"
    assert [chunk async for chunk in model.astream(["two"])] == ["local-chunk"]
    assert calls == [
        (["tool"], {"tool_choice": "propose_action"}),
        "paced",
        ["one"],
        "paced",
        ["two"],
    ]


@pytest.mark.asyncio
async def test_gate_refuses_existing_stop_without_calling_provider(helper):
    helper["LEDGER"].write_text('{"halt":"simulated isolated stop"}')
    with pytest.raises(AssertionError, match="Live testing stopped"):
        await helper["gate"]()
    assert not helper["RATE"].exists()
