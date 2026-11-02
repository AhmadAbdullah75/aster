"""Portable entry point selecting psycopg-compatible Windows asyncio before startup."""

import asyncio
import selectors
import sys

import uvicorn

if __name__ == "__main__":
    server = uvicorn.Server(
        uvicorn.Config("nexus.main:app", host="127.0.0.1", port=8000, loop="asyncio")
    )
    if sys.platform == "win32":
        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(server.serve())
