from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from .models import AuditEvent, Conversation, Note, Project, Task

RESOURCES: dict[str, Any] = {
    "projects": Project,
    "conversations": Conversation,
    "tasks": Task,
    "notes": Note,
}


def serialize(record) -> dict[str, Any]:
    return {
        c.key: getattr(record, c.key)
        for c in inspect(record).mapper.column_attrs
        if c.key not in {"password_hash", "token_hash", "blob", "user_id", "worker_id"}
    }


def owned(
    db: Session,
    model,
    resource_id: str,
    user_id: str,
    lock: bool = False,
    allow_deleting: bool = False,
):
    query = select(model).where(model.id == resource_id, model.user_id == user_id)
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None or (getattr(record, "deleting", False) and not allow_deleting):
        raise HTTPException(404, "Resource unavailable.")
    return record


def check_version(record, version: int | None):
    if version is None or record.version != version:
        raise HTTPException(409, "This item changed. Refresh it before saving.")


def save(db: Session, kind: str, user_id: str, payload: dict, resource_id: str | None = None):
    model = RESOURCES[kind]
    values = payload.copy()
    version = values.pop("version", None)
    if values.get("project_id"):
        owned(db, Project, values["project_id"], user_id, lock=True)
    if resource_id:
        record = owned(db, model, resource_id, user_id, lock=True)
        check_version(record, version)
        record.version += 1
        for key, value in values.items():
            setattr(record, key, value)
    else:
        record = model(user_id=user_id, **values)
        db.add(record)
    db.flush()
    db.add(AuditEvent(user_id=user_id, action=f"{kind}.save", resource_id=record.id))
    return serialize(record)


def remove(
    db: Session,
    kind: str,
    user_id: str,
    resource_id: str,
    version: int,
    allow_deleting: bool = False,
):
    record = owned(
        db, RESOURCES[kind], resource_id, user_id, lock=True, allow_deleting=allow_deleting
    )
    check_version(record, version)
    db.add(AuditEvent(user_id=user_id, action=f"{kind}.delete", resource_id=record.id))
    db.delete(record)
