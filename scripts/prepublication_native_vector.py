"""Provision a new, disposable benchmark database using current migrations."""

import argparse
import json
import os
import runpy
import subprocess
import sys

import psycopg
from prepublication_native_load import ROOT, configure, stopped
from psycopg import sql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    assert not stopped()
    admin, database = configure(args.run_id, 8012)
    evidence = ROOT / "artifacts/prepublication" / ("vector-native-" + args.run_id + ".json")
    assert not evidence.exists(), "Previous benchmark evidence preserved."
    with psycopg.connect(admin, autocommit=True) as db:
        assert not db.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
        ).fetchone(), "Existing database preserved; use a new run ID."
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    os.environ["ASTER_VECTOR_DATABASE"] = database
    os.environ["ASTER_VECTOR_REPORT"] = str(evidence)
    # The benchmark checks current_database and synthetic ownership again before
    # writing. It never receives the native app's database name as its target.
    runpy.run_path(str(ROOT / "scripts/prepublication_vector_benchmark.py"), run_name="__main__")
    if not stopped():
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
        report = json.loads(evidence.read_text())
        report.update(database=database, disposable_database_removed=True)
        evidence.write_text(json.dumps(report, indent=2) + "\n")
    print("Disposable native vector benchmark completed.")


if __name__ == "__main__":
    main()
