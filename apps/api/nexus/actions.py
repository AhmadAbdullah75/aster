from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from .db import transaction
from .memory import TransactionalStore, delete_memory_record, get_memory, save_memory
from .models import AuditEvent, Proposal, Run, User, now, uid
from .schemas import ActionPayload, Decision, MemoryInput, NoteInput, TaskInput
from .services import RESOURCES, check_version, owned, remove, save, serialize

INPUTS: dict[str, Any] = {"tasks": TaskInput, "notes": NoteInput, "memories": MemoryInput}


def proposal_fields(schema, values):
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise HTTPException(422, "Invalid proposal fields. " + details[:300]) from None


def validate_payload(db, action: str, payload: dict, user_id: str):
    kind, operation = action.split(".")
    if kind not in INPUTS or operation not in {"create", "update", "delete"}:
        raise HTTPException(422, "Unsupported action.")
    parsed = proposal_fields(ActionPayload, payload)
    for item in parsed.items:
        values = item.model_dump(exclude_none=True, exclude={"include", "id"})
        if kind == "memories" and not db.get(User, user_id).memory_enabled:
            raise HTTPException(409, "Memory is disabled in Settings.")
        if operation != "create":
            if not item.id or item.version is None:
                raise HTTPException(422, "Updates and deletions require an ID and current version.")
            if kind != "memories":
                check_version(owned(db, RESOURCES[kind], item.id, user_id), item.version)
        if operation != "delete":
            proposal_fields(INPUTS[kind], values)
        if item.project_id:
            from .models import Project

            owned(db, Project, item.project_id, user_id)
    return parsed.model_dump(mode="json")


def propose(user_id: str, thread_id: str, run_id: str, call_id: str, action: str, payload: dict):
    key = f"{run_id}:{call_id}"
    with transaction() as db:
        existing = db.scalar(select(Proposal).where(Proposal.idempotency_key == key))
        if existing:
            return serialize(existing)
        run = owned(db, Run, run_id, user_id, lock=True)
        if run.cancel_requested:
            raise InterruptedError("Canceled")
        valid = validate_payload(db, action, payload, user_id)
        # Allocate stable IDs before interruption; creates can be replayed safely.
        for item in valid["items"]:
            if action.endswith(".create"):
                item["id"] = uid()
        proposal = Proposal(
            user_id=user_id,
            conversation_id=thread_id,
            run_id=run_id,
            call_id=call_id,
            action=action,
            payload=valid,
            expires_at=now() + timedelta(days=7),
            idempotency_key=key,
        )
        db.add(proposal)
        db.flush()
        return serialize(proposal)


def decide(user_id: str, proposal_id: str, decision: Decision):
    with transaction() as db:
        proposal = owned(db, Proposal, proposal_id, user_id, lock=True)
        run = owned(db, Run, proposal.run_id, user_id, lock=True)
        replayable = proposal.status in {"completed", "rejected"} or (
            proposal.status == "approved"
            and not run.cancel_requested
            and proposal.expires_at > now()
        )
        if replayable and proposal.decision:
            previous = proposal.decision
            candidate = (
                decision.payload.model_dump(mode="json") if decision.payload else proposal.payload
            )
            if (
                decision.version == previous.get("version", 1)
                and decision.approve == previous["approve"]
                and (not decision.approve or candidate == previous["payload"])
            ):
                return {**serialize(proposal), "already_decided": True}
            raise HTTPException(
                409, "This proposal already has a different decision. Refresh the conversation."
            )
        check_version(proposal, decision.version)
        if (
            proposal.status != "pending"
            or proposal.expires_at <= now()
            or run.cancel_requested
            or run.status != "waiting"
        ):
            raise HTTPException(
                409, "Proposal is stale, expired or already decided. Refresh the conversation."
            )
        valid = proposal.payload
        if decision.approve:
            valid = validate_payload(
                db,
                proposal.action,
                decision.payload.model_dump(mode="json") if decision.payload else proposal.payload,
                user_id,
            )
            if len(valid["items"]) != len(proposal.payload["items"]):
                raise HTTPException(422, "Exclude items instead of adding or removing them.")
            for old, new in zip(proposal.payload["items"], valid["items"], strict=True):
                if (
                    old.get("id") != new.get("id")
                    or old.get("project_id") != new.get("project_id")
                    or old.get("version") != new.get("version")
                ):
                    raise HTTPException(
                        422, "Changing target, project or version requires a new proposal."
                    )
        proposal.decision = {
            "approve": decision.approve,
            "payload": valid,
            "version": decision.version,
        }
        proposal.status = "approved" if decision.approve else "rejected"
        proposal.version += 1
        db.add(
            AuditEvent(
                user_id=user_id,
                action="proposal.decision",
                resource_id=proposal.id,
                detail={"approved": decision.approve},
            )
        )
        db.flush()
        pending = db.scalar(
            select(Proposal.id).where(Proposal.run_id == run.id, Proposal.status == "pending")
        )
        if pending is None:
            run.status = "queued"
            run.input = {**run.input, "resume": True}
        return serialize(proposal)


async def execute(store, user_id: str, proposal_id: str):
    # Transaction row locks and persisted outcome cover crash-after-write-before-checkpoint.
    with transaction() as db:
        proposal = owned(db, Proposal, proposal_id, user_id, lock=True)
        run = owned(db, Run, proposal.run_id, user_id, lock=True)
        if proposal.outcome is not None:
            return proposal.outcome
        if run.cancel_requested:
            proposal.status = "stale"
            return {"status": "canceled", "saved": []}
        if proposal.status == "rejected":
            proposal.outcome = {"status": "rejected", "saved": []}
            return proposal.outcome
        if proposal.status != "approved" or proposal.expires_at <= now():
            raise HTTPException(409, "Action has no valid approval.")
        valid = validate_payload(db, proposal.action, proposal.decision["payload"], user_id)
        kind, operation = proposal.action.split(".")
        if kind == "memories":
            db.execute(select(User).where(User.id == user_id).with_for_update())
            store = TransactionalStore(db)
        outcomes = []
        for item in valid["items"]:
            if not item["include"]:
                continue
            values = {k: v for k, v in item.items() if v is not None and k not in {"id", "include"}}
            if kind == "memories":
                if operation == "delete":
                    await delete_memory_record(store, user_id, item["id"], item["version"])
                    outcomes.append({"id": item["id"], "deleted": True})
                else:
                    previous = await get_memory(store, user_id, item["id"])
                    if operation == "create" and previous:
                        outcomes.append({"id": item["id"], **previous.value})
                    else:
                        result = await save_memory(
                            store,
                            user_id,
                            MemoryInput.model_validate(values),
                            item["id"] if operation == "update" else None,
                            f"Conversation {proposal.conversation_id}",
                            create_id=item["id"],
                        )
                        outcomes.append(result)
            elif operation == "delete":
                remove(db, kind, user_id, item["id"], item["version"])
                outcomes.append({"id": item["id"], "deleted": True})
            else:
                clean = INPUTS[kind].model_validate(values).model_dump()
                result = save(
                    db, kind, user_id, clean, item["id"] if operation == "update" else None
                )
                outcomes.append(
                    {k: str(v) if hasattr(v, "isoformat") else v for k, v in result.items()}
                )
        proposal.outcome = {"status": "completed", "saved": outcomes}
        proposal.status = "completed"
        proposal.version += 1
        db.add(AuditEvent(user_id=user_id, action="proposal.executed", resource_id=proposal.id))
        return proposal.outcome
