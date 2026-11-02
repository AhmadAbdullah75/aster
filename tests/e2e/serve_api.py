"""Isolated e2e server: normal API, separate PostgreSQL, provider disabled."""

import asyncio
import os
import selectors
import subprocess
import sys
from pathlib import Path

import psycopg
import uvicorn
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
private_settings = dotenv_values(root / ".env")
url = str(private_settings["DATABASE_URL"]).replace(
    "postgresql+psycopg://", "postgresql://"
)
with psycopg.connect(url, autocommit=True) as connection:
    if not connection.execute("SELECT 1 FROM pg_database WHERE datname='nexus_e2e'").fetchone():
        connection.execute("CREATE DATABASE nexus_e2e")
os.environ["DATABASE_URL"] = (
    url.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + "/nexus_e2e"
)
os.environ["APP_ORIGIN"] = "http://127.0.0.1:3001"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""
os.environ["WEB_BACKEND"] = "ddgs"
os.environ["AI_PROVIDER"] = "gemini"
# Explicit isolated queue-only runs exercise the real RunInput/API boundary.
# No worker is started here and this value is deliberately not a provider key.
if os.environ.get("NEXUS_E2E_REAL_PROVIDER") == "true":
    assert os.environ.get("NEXUS_LIVE_PREPUBLICATION") == "true"
    assert os.environ.get("NEXUS_LIVE_FLOW") == "true"
    assert private_settings.get("GEMINI_API_KEY"), "A live free-tier key must be entered privately in .env"
    os.environ["GEMINI_API_KEY"] = str(private_settings["GEMINI_API_KEY"])
    os.environ["WEB_BACKEND"] = str(private_settings.get("WEB_BACKEND", "ddgs"))
    os.environ["TAVILY_API_KEY"] = str(private_settings.get("TAVILY_API_KEY", ""))
    os.environ["FREE_ONLY"] = "true"
elif os.environ.get("NEXUS_E2E_QUEUE_ONLY") == "true":
    os.environ["AI_PROVIDER"] = "openai"
    os.environ["FREE_ONLY"] = "false"
    os.environ["OPENAI_API_KEY"] = "synthetic-queue-only-no-provider-access"
os.environ["DATA_DIR"] = str(root / ".data" / "e2e")
os.environ["PYTHONPATH"] = str(root / "apps" / "api")
sys.path.insert(0, os.environ["PYTHONPATH"])
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True)
subprocess.run([sys.executable, "-m", "nexus.migrate_graph"], cwd=root, check=True)
if os.environ.get("NEXUS_E2E_PRESERVE_DATA") != "true":
    with psycopg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as connection:
        connection.execute(
            "TRUNCATE users, rate_buckets, store, checkpoints, checkpoint_blobs, checkpoint_writes CASCADE"
        )
server = uvicorn.Server(
    uvicorn.Config("nexus.main:app", host="127.0.0.1", port=8001, access_log=False)
)
if sys.platform == "win32":
    asyncio.run(
        server.serve(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    )
else:
    asyncio.run(server.serve())
