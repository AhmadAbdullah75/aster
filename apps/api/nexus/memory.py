from fastapi import HTTPException
from langgraph.store.postgres import PostgresStore

from .db import transaction
from .models import Project, now, uid
from .schemas import MemoryInput
from .services import owned


class TransactionalStore:
    """LangGraph store bound to the ORM's psycopg transaction for atomic approved actions.

    These short local DB calls intentionally do not yield to another task. Normal runtime
    retrieval uses AsyncPostgresStore; no store schema is duplicated or directly manipulated.
    """

    def __init__(self, db):
        self.store = PostgresStore(db.connection().connection.driver_connection)

    async def aget(self, ns, key):
        return self.store.get(ns, key)

    async def aput(self, ns, key, value):
        self.store.put(ns, key, value)

    async def adelete(self, ns, key):
        self.store.delete(ns, key)

    async def asearch(self, ns, **kwargs):
        return self.store.search(ns, **kwargs)


def namespace(user_id: str, project_id: str | None = None):
    base = ("users", user_id, "memories")
    return (*base, project_id) if project_id else base


async def get_memory(store, user_id: str, memory_id: str):
    direct = await store.aget(namespace(user_id), memory_id)
    if direct:
        return direct
    return next(
        (m for m in await store.asearch(namespace(user_id), limit=1000) if m.key == memory_id), None
    )


async def delete_memory_record(store, user_id: str, memory_id: str, version: int):
    item = await get_memory(store, user_id, memory_id)
    if not item:
        raise HTTPException(404, "Memory unavailable.")
    if item.value["version"] != version:
        raise HTTPException(409, "Memory changed; refresh first.")
    await store.adelete(namespace(user_id, item.value.get("project_id")), memory_id)


async def list_memories(store, user_id: str):
    items = await store.asearch(namespace(user_id), limit=1000)
    return [{"id": item.key, **item.value} for item in items]


async def save_memory(
    store,
    user_id: str,
    payload: MemoryInput,
    memory_id: str | None = None,
    provenance: str = "User form",
    create_id: str | None = None,
):
    if payload.project_id:
        with transaction() as db:
            owned(db, Project, payload.project_id, user_id)
    previous = await get_memory(store, user_id, memory_id) if memory_id else None
    if memory_id and previous is None:
        raise HTTPException(404, "Memory unavailable.")
    if previous and payload.version != previous.value["version"]:
        raise HTTPException(409, "Memory changed. Refresh before saving.")
    value = payload.model_dump(mode="json", exclude={"version"})
    value.update(
        version=(previous.value["version"] + 1 if previous else 1),
        created_at=previous.value["created_at"] if previous else now().isoformat(),
        updated_at=now().isoformat(),
        provenance=previous.value.get("provenance", provenance) if previous else provenance,
    )
    key = memory_id or create_id or uid()
    if not previous and len(await list_memories(store, user_id)) >= 1000:
        raise HTTPException(413, "Memory limit reached. Delete unused memories first.")
    await store.aput(namespace(user_id, payload.project_id), key, value)
    if previous and previous.value.get("project_id") != payload.project_id:
        await store.adelete(namespace(user_id, previous.value.get("project_id")), key)
    return {"id": key, **value}


async def relevant_memories(store, user_id: str, query: str, project_id: str | None):
    memories = await list_memories(store, user_id)
    words = set(query.lower().split())
    eligible = [m for m in memories if m["enabled"] and m.get("project_id") in (None, project_id)]
    eligible.sort(
        key=lambda m: (
            m["category"] == "preference",
            len(words & set(m["content"].lower().split())),
            m["updated_at"],
        ),
        reverse=True,
    )
    return eligible[:5]
