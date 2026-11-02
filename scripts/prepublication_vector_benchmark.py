"""Real1536-D pgvector/FTS timings on10k/100k synthetic chunks in disposable Docker DB."""

import json
import os
import shutil
import statistics
import time
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from prepublication_native_load import stopped

ROOT = Path(__file__).resolve().parents[1]
evidence = Path(
    os.environ.get(
        "ASTER_VECTOR_REPORT", str(ROOT / "artifacts/prepublication/vector-performance.json")
    )
).resolve()
assert evidence.is_relative_to(ROOT / "artifacts/prepublication")
if os.environ.get("ASTER_VECTOR_DATABASE"):
    assert not evidence.exists(), "Preserve previous benchmark evidence; choose a new run ID."
assert shutil.disk_usage(ROOT).free >= 10 * 1024**3, "Scale benchmark requires at least10GiB free."
native_database = os.environ.get("ASTER_VECTOR_DATABASE", "")
if native_database:
    import re

    assert re.fullmatch(r"nexus_perf_[a-z0-9_]{1,35}", native_database)
    native_url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    assert native_url.rsplit("/", 1)[1] == native_database
else:
    env = dotenv_values(ROOT / ".data/prepublication-docker/test.env")
    assert env["POSTGRES_DB"] == "nexus_publication"
identity = str(uuid.uuid4())
docs = [str(uuid.uuid4()) for _ in range(84)]
vector = "[1,0.31," + ",".join(["0"] * 1534) + "]"
report = {
    "scope": "Actual scoped pgvector/FTS SQL,1536dimensions; synthetic vectors, no provider latency. Dedicated measurement on shared local host; no concurrent load/build batch.",
    "samples": [],
}
connection = (
    native_url
    if native_database
    else dict(
        host="127.0.0.1",
        port=5435,
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
    )
)

with (
    psycopg.connect(connection, autocommit=True)
    if native_database
    else psycopg.connect(**connection, autocommit=True) as db
):
    assert db.execute("SELECT current_database()").fetchone()[0] == (
        native_database or "nexus_publication"
    )
    db.execute(
        "INSERT INTO users(id,email,password_hash,name,timezone,memory_enabled,theme,version,created_at,updated_at) VALUES(%s,%s,'unused-synthetic-hash','Vector performance','UTC',false,'light',1,now(),now())",
        (identity, f"publication-vector-{identity}@example.com"),
    )
    try:
        with db.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents(id,user_id,filename,blob,sha256,size,media_type,status,embedding_model,embedding_dimensions,version,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,1000,'text/plain','ready','gemini-embedding-2',1536,1,now(),now())",
                [
                    (
                        doc,
                        identity,
                        f"Synthetic benchmark{number}.txt",
                        f"no-original-{doc}.txt",
                        doc,
                    )
                    for number, doc in enumerate(docs)
                ],
            )
        for start, end in [(1, 10_000), (10_001, 100_000)]:
            assert shutil.disk_usage(ROOT).free >= 10 * 1024**3, (
                "Disk reserve too low for more vectors."
            )
            assert not stopped()
            started = time.monotonic()
            db.execute(
                """INSERT INTO chunks(id,user_id,document_id,position,section,content,embedding,version,created_at,updated_at)
                SELECT md5(%s || g::text)::uuid::text,%s,(%s::text[])[((g-1)/1200)+1],(g-1)%%1200,'Synthetic performance',
                'Synthetic acceptance benchmark marker ' || g::text,
                (ARRAY[1::real,(g%%97)::real/97] || array_fill(0::real,ARRAY[1534]))::vector,1,now(),now()
                FROM generate_series(%s::int,%s::int) g""",
                (identity, identity, docs, start, end),
            )
            db.execute("ANALYZE chunks")
            insert_seconds = time.monotonic() - started
            dense_sql = """EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) SELECT c.*,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE c.user_id=%s AND d.user_id=%s AND d.status='ready' AND d.embedding_model='gemini-embedding-2' AND d.embedding_dimensions=1536
                ORDER BY c.embedding <=> %s::vector LIMIT18""".replace("LIMIT18", "LIMIT 18")
            sparse_sql = """EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) SELECT c.*,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE c.user_id=%s AND d.user_id=%s AND d.status='ready' AND d.embedding_model='gemini-embedding-2' AND d.embedding_dimensions=1536
                AND to_tsvector('english',c.content) @@ websearch_to_tsquery('english','acceptance')
                ORDER BY ts_rank_cd(to_tsvector('english',c.content),websearch_to_tsquery('english','acceptance')) DESC LIMIT18""".replace(
                "LIMIT18", "LIMIT 18"
            )
            measurements = []
            for _ in range(3):
                dense = db.execute(dense_sql, (identity, identity, vector)).fetchone()[0][0]
                sparse = db.execute(sparse_sql, (identity, identity)).fetchone()[0][0]
                assert dense["Plan"]["Actual Rows"] == sparse["Plan"]["Actual Rows"] == 18
                measurements.append(
                    {
                        "dense_ms": dense["Execution Time"],
                        "sparse_ms": sparse["Execution Time"],
                        "combined_db_ms": dense["Execution Time"] + sparse["Execution Time"],
                    }
                )
            median = statistics.median(x["combined_db_ms"] for x in measurements)
            report["samples"].append(
                {
                    "chunks": end,
                    "insert_seconds": round(insert_seconds, 3),
                    "measurements": measurements,
                    "median_combined_db_ms": median,
                    "dense_plan": dense,
                    "sparse_plan": sparse,
                }
            )
            evidence.write_text(json.dumps(report, indent=2) + "\n")
            print(f"{end} chunks: median dense+FTS DB time {median:.2f}ms", flush=True)
        report["ten_thousand_under_one_second"] = (
            report["samples"][0]["median_combined_db_ms"] < 1000
        )
        report["ann_decision"] = (
            "Recommend measuring a scoped ANN index before production at100k chunks; sequential vector scan exceeds1s here."
            if report["samples"][1]["median_combined_db_ms"] >= 1000
            else "No ANN index required by this local100k timing; remeasure production data distribution and concurrency before scaling."
        )
    finally:
        if stopped():
            raise SystemExit(75)
        report["synthetic_rows_cleaned"] = False
        try:
            if not db.closed:
                db.execute(
                    "DELETE FROM users WHERE id=%s AND email=%s",
                    (identity, f"publication-vector-{identity}@example.com"),
                )
                report["synthetic_rows_cleaned"] = (
                    db.execute(
                        "SELECT count(*) FROM chunks WHERE user_id=%s", (identity,)
                    ).fetchone()[0]
                    == 0
                )
        except psycopg.Error:
            report["cleanup_pending"] = (
                "Database unavailable; remove only this synthetic namespace after recovery."
            )
        evidence.write_text(json.dumps(report, indent=2) + "\n")
