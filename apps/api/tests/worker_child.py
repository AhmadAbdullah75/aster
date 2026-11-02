"""Test-only slow provider process for hard worker-crash recovery verification."""

import asyncio
import sys

from langchain_core.messages import AIMessageChunk
from nexus.graph_resources import resources
from nexus.worker import claim_run, process_run


class SlowProvider:
    def bind_tools(self, *args, **kwargs):
        return self

    async def astream(self, messages):
        yield AIMessageChunk(content="Interrupted synthetic generation " * 5)
        await asyncio.sleep(300)


async def main():
    async with resources() as (saver, store):
        await process_run(claim_run("crash-child"), "crash-child", saver, store, SlowProvider())


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
