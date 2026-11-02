"""Constraint probes against the disposable Docker database on localhost5435 only."""

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
values = dotenv_values(ROOT / ".data/prepublication-docker/test.env")
assert values["POSTGRES_DB"] == "nexus_publication"
connection = dict(
    host="127.0.0.1",
    port=5435,
    dbname=values["POSTGRES_DB"],
    user=values["POSTGRES_USER"],
    password=values["POSTGRES_PASSWORD"],
)
user, thread = str(uuid.uuid4()), str(uuid.uuid4())
with psycopg.connect(**connection) as db:
    assert db.execute("SELECT current_database()").fetchone()[0] == "nexus_publication"
    constraints = db.execute(
        "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_type='FOREIGN KEY' AND table_schema='public'"
    ).fetchone()[0]
    assert constraints >= 15
    try:
        with db.transaction():
            db.execute(
                "INSERT INTO projects(id,user_id,title,description,instructions,deleting,version,created_at,updated_at) VALUES(%s,%s,'Orphan probe','','',false,1,now(),now())",
                (str(uuid.uuid4()), str(uuid.uuid4())),
            )
    except psycopg.errors.ForeignKeyViolation:
        orphan_blocked = True
    else:
        raise AssertionError("Orphan project was accepted")
    db.execute(
        "INSERT INTO users(id,email,password_hash,name,timezone,memory_enabled,theme,version,created_at,updated_at) VALUES(%s,%s,'unused-synthetic-hash','Constraint probe','UTC',true,'light',1,now(),now())",
        (user, f"publication-constraints-{user}@example.com"),
    )
    db.execute(
        "INSERT INTO conversations(id,user_id,title,archived,deleting,version,created_at,updated_at) VALUES(%s,%s,'Parallel constraint probe',false,false,1,now(),now())",
        (thread, user),
    )
    created = db.execute("SELECT created_at FROM conversations WHERE id=%s", (thread,)).fetchone()[
        0
    ]
    assert created.utcoffset() == timedelta(0)
    naive = db.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name IN ('created_at','updated_at','expires_at','lease_until') AND data_type='timestamp without time zone'"
    ).fetchone()[0]
    assert naive == 0

barrier = threading.Barrier(2)


def insert_run(_):
    barrier.wait(timeout=10)
    try:
        with psycopg.connect(**connection) as db:
            db.execute(
                "INSERT INTO runs(id,user_id,conversation_id,status,input,cancel_requested,attempts,seq,version,created_at,updated_at) VALUES(%s,%s,%s,'queued','{}',false,0,0,1,now(),now())",
                (str(uuid.uuid4()), user, thread),
            )
        return "committed"
    except psycopg.errors.UniqueViolation:
        return "unique_conflict"


try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(insert_run, range(2)))
    assert outcomes == ["committed", "unique_conflict"]
    with psycopg.connect(**connection) as db:
        assert (
            db.execute("SELECT count(*) FROM runs WHERE conversation_id=%s", (thread,)).fetchone()[
                0
            ]
            == 1
        )
finally:
    with psycopg.connect(**connection) as db:
        db.execute(
            "DELETE FROM users WHERE id=%s AND email=%s",
            (user, f"publication-constraints-{user}@example.com"),
        )
        assert (
            db.execute("SELECT count(*) FROM conversations WHERE id=%s", (thread,)).fetchone()[0]
            == 0
        )
        assert (
            db.execute("SELECT count(*) FROM runs WHERE conversation_id=%s", (thread,)).fetchone()[
                0
            ]
            == 0
        )
report = {
    "database": "nexus_publication",
    "foreign_keys": constraints,
    "orphan_project_blocked": orphan_blocked,
    "parallel_run_inserts": outcomes,
    "naive_timestamp_columns": naive,
    "created_offset_seconds": created.utcoffset().total_seconds(),
    "synthetic_relational_cleanup": True,
}
(ROOT / "artifacts/prepublication/database-integrity.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(json.dumps(report))
