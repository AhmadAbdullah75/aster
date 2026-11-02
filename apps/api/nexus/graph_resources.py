from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings


@asynccontextmanager
async def resources(migrate: bool = False):
    async with AsyncConnectionPool(
        settings.pg_url,
        min_size=1,
        max_size=8,
        open=False,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        typed_pool: Any = pool
        await pool.wait(timeout=10)
        saver = AsyncPostgresSaver(typed_pool)
        store = AsyncPostgresStore(typed_pool)
        if migrate:
            await saver.setup()
            await store.setup()
        yield saver, store
