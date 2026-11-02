import asyncio
import sys

from .graph_resources import resources


async def main():
    async with resources(migrate=True):
        print("LangGraph checkpoint/store migrations complete.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
