"""Seed only large synthetic collection boundaries in isolated nexus_e2e."""

import asyncio
import json
import sys

import graph_fixture  # noqa: F401 -- isolated environment initialization
from nexus.db import transaction
from nexus.memory import TransactionalStore, namespace
from nexus.models import Project, Task, User, now, uid
from sqlalchemy import text


async def main():
    mode, user_id = sys.argv[1:3]
    with transaction() as db:
        assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
        user = db.get(User, user_id)
        assert (
            user
            and user.email.startswith("publication-collection-")
            and user.email.endswith("@example.com")
        )
        if mode == "tasks":
            projects = [
                Project(user_id=user_id, title=f"Collection scope {letter}")
                for letter in ("A", "B")
            ]
            db.add_all(projects)
            db.flush()
            tasks = []
            for index in range(150):
                item = Task(
                    user_id=user_id,
                    title=f"Pagination task{index:03d}",
                    project_id=projects[index % 2].id,
                    status=["todo", "in_progress", "done"][index % 3],
                    priority=["low", "medium", "high"][(index // 3) % 3],
                )
                db.add(item)
                db.flush()
                tasks.append(
                    {
                        "title": item.title,
                        "status": item.status,
                        "priority": item.priority,
                        "project_id": item.project_id,
                    }
                )
            result = {
                "tasks": tasks,
                "projects": [{"id": p.id, "title": p.title} for p in projects],
            }
        elif mode == "memories":
            store = TransactionalStore(db)
            for index in range(1000):
                await store.aput(
                    namespace(user_id),
                    uid(),
                    {
                        "title": f"Boundary memory{index:04d}",
                        "content": "Boundary fixture content",
                        "category": "preference",
                        "enabled": True,
                        "project_id": None,
                        "version": 1,
                        "created_at": now().isoformat(),
                        "updated_at": now().isoformat(),
                        "provenance": "Synthetic boundary fixture",
                    },
                )
            result = {"count": 1000, "authoritative_store_api": True}
        elif mode == "projects":
            db.add_all(
                [
                    Project(user_id=user_id, title=f"Collection project{index:02d}")
                    for index in range(50)
                ]
            )
            result = {"count": 50}
        else:
            raise AssertionError("Unsupported collection fixture")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
