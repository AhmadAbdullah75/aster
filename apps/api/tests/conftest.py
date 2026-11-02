import asyncio
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
values = dotenv_values(ROOT / ".env")
url = str(values["DATABASE_URL"]).replace("postgresql+psycopg://", "postgresql://")
test_url = url.rsplit("/", 1)[0] + "/nexus_test"
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
with psycopg.connect(url, autocommit=True) as connection:
    if not connection.execute("SELECT 1 FROM pg_database WHERE datname='nexus_test'").fetchone():
        connection.execute("CREATE DATABASE nexus_test")
os.environ["DATABASE_URL"] = test_url.replace("postgresql://", "postgresql+psycopg://")
os.environ["DATA_DIR"] = str(ROOT / ".data" / "test")
os.environ["AI_PROVIDER"] = "openai"
os.environ["FREE_ONLY"] = "false"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""
os.environ["WEB_BACKEND"] = "ddgs"
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
subprocess.run([sys.executable, "-m", "nexus.migrate_graph"], cwd=ROOT, check=True)

from fastapi.testclient import TestClient  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import engine  # noqa: E402
from nexus.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    with engine.begin() as db:
        from sqlalchemy import text

        db.execute(
            text(
                "TRUNCATE users, rate_buckets, store, checkpoints, checkpoint_blobs, checkpoint_writes CASCADE"
            )
        )
    yield


@pytest.fixture
def client():
    with TestClient(app, headers={"origin": settings.app_origin}) as c:
        yield c


def register(client, email="alice@example.com"):
    result = client.post(
        "/auth/register",
        json={"email": email, "password": "synthetic-test-password", "name": email.split("@")[0]},
    )
    assert result.status_code == 200, result.text
    return result.json()
