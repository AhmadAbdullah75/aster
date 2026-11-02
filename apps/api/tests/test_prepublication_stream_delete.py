"""An authorized SSE connection must end cleanly when its canonical run is deleted."""

import asyncio
from types import SimpleNamespace

import pytest
from nexus.db import transaction
from nexus.events import emit
from nexus.main import stream
from nexus.models import Conversation, User
from test_graph import setup_run


@pytest.mark.asyncio
async def test_open_event_stream_ends_without_http_exception_after_parent_deletion(
    client, monkeypatch
):
    account, thread, run = setup_run(client, monkeypatch)
    emit(run.id, "run.started", {"status": "running"})
    with transaction() as db:
        user = db.get(User, account["id"])

    async def connected():
        return False

    response = await stream(run.id, user, SimpleNamespace(is_disconnected=connected), cursor=0)
    iterator = response.body_iterator
    async with asyncio.timeout(2):
        first = await anext(iterator)
        assert "run." in first
        with transaction() as db:
            db.delete(db.get(Conversation, thread["id"]))
        # Rows already selected before deletion may finish the current batch.
        # The next poll must finish normally rather than raise HTTP404 after headers.
        async for _ in iterator:
            pass
