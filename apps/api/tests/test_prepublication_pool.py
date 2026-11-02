"""Only terminate a known idle pool connection in the isolated test database."""

import pytest
from nexus.db import transaction
from nexus.graph_resources import resources
from sqlalchemy import text


@pytest.mark.asyncio
async def test_memory_pool_replaces_dead_idle_connection_before_next_request():
    async with resources() as (_, store):
        async with store.conn.connection() as connection:
            cursor = await connection.execute("SELECT pg_backend_pid() AS pid, current_database() AS database")
            row = await cursor.fetchone()
            assert row["database"] == "nexus_test"
            pid = row["pid"]
        with transaction() as db:
            assert db.scalar(text("SELECT current_database()")) == "nexus_test"
            terminated = db.scalar(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid=:pid AND datname='nexus_test'"), {"pid": pid})
            assert terminated is True
        assert await store.asearch(("publication-pool-regression",), limit=1) == []
