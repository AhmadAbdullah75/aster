"""Reset synthetic case state ONLY in the disposable e2e database."""

from pathlib import Path

import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
url = str(dotenv_values(root / ".env")["DATABASE_URL"]).replace(
    "postgresql+psycopg://", "postgresql://"
)
test_url = url.rsplit("/", 1)[0] + "/nexus_e2e"
with psycopg.connect(test_url, autocommit=True) as connection:
    assert connection.execute("SELECT current_database()").fetchone()[0] == "nexus_e2e"
    connection.execute(
        "TRUNCATE users, rate_buckets, store, checkpoints, checkpoint_blobs, checkpoint_writes CASCADE"
    )
