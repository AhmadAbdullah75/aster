import asyncio
import hashlib
import json
import sys
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from . import documents
from .actions import decide
from .config import settings
from .db import engine, transaction
from .events import emit
from .graph_resources import resources
from .limits import BodyLimitMiddleware
from .memory import TransactionalStore, delete_memory_record, list_memories, namespace, save_memory
from .models import (
    Chunk,
    Conversation,
    Document,
    IngestionJob,
    Message,
    Project,
    Proposal,
    Run,
    RunEvent,
    Session,
    Task,
    User,
)
from .schemas import (
    ConversationInput,
    Credentials,
    Decision,
    MemoryInput,
    NoteInput,
    Profile,
    ProjectInput,
    RunInput,
    TaskInput,
)
from .security import allowed_origin, current_user, digest, hasher, limit, set_session, verify
from .services import RESOURCES, check_version, owned, remove, save, serialize

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    if len(settings.session_secret) < 32:
        raise RuntimeError("Run scripts/init_env.py to generate the local .env first.")
    async with resources() as (saver, store):
        app.state.saver, app.state.store = saver, store
        yield
    engine.dispose()


app = FastAPI(title="Aster API", version="0.1.0", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)
Auth = Annotated[User, Depends(current_user)]


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not allowed_origin(request.headers.get("origin")):
            return JSONResponse(
                {
                    "detail": "This address is not allowed to submit requests to Aster. Use the configured website address."
                },
                status_code=403,
            )
        length = request.headers.get("content-length")
        maximum = (
            (settings.upload_limit_mib + 1) * 1024 * 1024
            if request.url.path == "/documents"
            else 512 * 1024
        )
        if length and int(length) > maximum:
            return Response("Request body too large.", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as db:
            db.execute(text("SELECT 1 FROM alembic_version"))
            db.execute(text("SELECT 1 FROM checkpoint_migrations LIMIT 1"))
            db.execute(text("SELECT 1 FROM store_migrations LIMIT 1"))
        return {"database": True, "ai_configured": bool(settings.provider_key)}
    except Exception:
        raise HTTPException(503, "Database or migrations unavailable.") from None


@app.post("/auth/register")
def register(payload: Credentials, request: Request, response: Response):
    limit(
        "register:"
        + hashlib.sha256((request.client.host if request.client else "local").encode()).hexdigest(),
        8,
        3600,
    )
    try:
        with transaction() as db:
            user = User(
                email=str(payload.email).lower(),
                name=payload.name,
                password_hash=hasher.hash(payload.password),
            )
            db.add(user)
            db.flush()
            result = serialize(user)
    except IntegrityError:
        raise HTTPException(409, "An account with this email already exists.") from None
    set_session(response, result["id"])
    return result


@app.post("/auth/login")
def login(payload: Credentials, request: Request, response: Response):
    key = hashlib.sha256(
        (str(payload.email).lower() + (request.client.host if request.client else "local")).encode()
    ).hexdigest()
    limit("login:" + key, 10, 300)
    with transaction() as db:
        user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
        if not user or not verify(payload.password, user.password_hash):
            raise HTTPException(401, "Incorrect email or password.")
        result = serialize(user)
    set_session(response, result["id"])
    return result


@app.post("/auth/logout")
def logout(request: Request, response: Response, user: Auth):
    with transaction() as db:
        db.execute(
            delete(Session).where(
                Session.token_hash == digest(request.cookies.get("nexus_session", ""))
            )
        )
    response.delete_cookie("nexus_session", path="/")
    return {"ok": True}


@app.get("/me")
def me(user: Auth):
    return serialize(user)


@app.put("/me")
def profile(payload: Profile, user: Auth):
    with transaction() as db:
        record = db.scalar(select(User).where(User.id == user.id).with_for_update())
        check_version(record, payload.version)
        for key, value in payload.model_dump(exclude={"version"}).items():
            setattr(record, key, value)
        record.version += 1
        return serialize(record)


@app.get("/capabilities")
def capabilities(user: Auth):
    available = bool(settings.provider_key)
    reason = (
        None
        if available
        else f"Add {settings.key_name} directly to root .env and restart API and worker."
    )
    try:
        settings.assert_provider_policy()
    except ValueError as exc:
        available, reason = False, str(exc)
    return {
        "chat": available,
        "embeddings": available,
        "web": available,
        "reason": reason,
        "models": {
            "chat": settings.chat_model,
            "search": "DDGS / DuckDuckGo (no API key)"
            if settings.web_backend == "ddgs"
            else "Tavily (basic search)" if settings.web_backend == "tavily"
            else settings.search_model,
            "embedding": settings.embedding_model,
        },
        "connection": "Configured; live account access requires a successful request."
        if available
        else "Provider key missing",
        "upload_limit_mib": settings.upload_limit_mib,
    }


SCHEMAS = {
    "projects": ProjectInput,
    "conversations": ConversationInput,
    "tasks": TaskInput,
    "notes": NoteInput,
}


# Register concrete schemas per resource so OpenAPI remains generated and precise.
def resource_routes(kind, schema):
    model = RESOURCES[kind]

    def listing(
        user: Auth,
        q: str = "",
        project_id: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        status: str | None = None,
        priority: str | None = None,
    ):
        with transaction() as db:
            query = select(model).where(model.user_id == user.id)
            if q:
                match = model.title.ilike(f"%{q[:200]}%")
                if kind == "notes":
                    match = or_(match, model.content.ilike(f"%{q[:200]}%"))
                query = query.where(match)
            if project_id and hasattr(model, "project_id"):
                owned(db, Project, project_id, user.id)
                query = query.where(model.project_id == project_id)
            if kind == "tasks" and status:
                query = query.where(Task.status == status)
            if kind == "tasks" and priority:
                query = query.where(Task.priority == priority)
            return [
                serialize(r)
                for r in db.scalars(
                    query.order_by(model.updated_at.desc(), model.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def get_item(resource_id: str, user: Auth):
        with transaction() as db:
            return serialize(owned(db, model, resource_id, user.id))

    def create_item(payload, user: Auth):
        with transaction() as db:
            return save(db, kind, user.id, payload.model_dump())

    def update_item(resource_id: str, payload, user: Auth):
        with transaction() as db:
            return save(db, kind, user.id, payload.model_dump(), resource_id)

    async def delete_item(resource_id: str, version: int, user: Auth, request: Request):
        await delete_resource(kind, resource_id, version, user.id, request)
        return {"ok": True}

    create_item.__annotations__["payload"] = schema
    update_item.__annotations__["payload"] = schema
    routes: list[tuple[str, Any, str]] = [
        (f"/{kind}", listing, "GET"),
        (f"/{kind}", create_item, "POST"),
        (f"/{kind}/{{resource_id}}", get_item, "GET"),
        (f"/{kind}/{{resource_id}}", update_item, "PUT"),
        (f"/{kind}/{{resource_id}}", delete_item, "DELETE"),
    ]
    for path, endpoint, method in routes:
        app.add_api_route(path, endpoint, methods=[method], name=f"{kind}_{endpoint.__name__}")


async def delete_resource(kind, resource_id, version, user_id, request):
    blobs, thread_ids = [], []
    with transaction() as db:
        record = owned(db, RESOURCES[kind], resource_id, user_id, lock=True, allow_deleting=True)
        check_version(record, version)
        if hasattr(record, "deleting"):
            record.deleting = True
        if kind == "conversations":
            thread_ids = [resource_id]
        elif kind == "projects":
            thread_ids = list(
                db.scalars(
                    select(Conversation.id).where(
                        Conversation.project_id == resource_id, Conversation.user_id == user_id
                    )
                )
            )
            blobs = list(
                db.scalars(
                    select(Document.blob).where(
                        Document.project_id == resource_id, Document.user_id == user_id
                    )
                )
            )
    # Commit the parent fence before acquiring run locks. Approved actions also lock
    # project rows; retaining that lock while canceling runs would invert lock order.
    with transaction() as db:
        for conversation in db.scalars(select(Conversation).where(Conversation.id.in_(thread_ids))):
            conversation.deleting = True
        for run in db.scalars(select(Run).where(Run.conversation_id.in_(thread_ids))):
            run.cancel_requested = True
    # Worker owns this advisory lock throughout graph execution. Cancel first, await its exit,
    # then remove checkpoints while holding the same lock so no checkpoint can resurrect.
    for thread_id in sorted(thread_ids):
        async with request.app.state.saver.conn.connection() as connection:
            await connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (thread_id,))
            try:
                await request.app.state.saver.adelete_thread(thread_id)
            finally:
                await connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (thread_id,))
    with transaction() as db:
        remove(db, kind, user_id, resource_id, version, allow_deleting=True)
    for blob in blobs:
        (settings.blobs / blob).unlink(missing_ok=True)
    if kind == "projects":
        for memory in await list_memories(request.app.state.store, user_id):
            if memory.get("project_id") == resource_id:
                await request.app.state.store.adelete(namespace(user_id, resource_id), memory["id"])


for resource_kind, resource_schema in SCHEMAS.items():
    resource_routes(resource_kind, resource_schema)


@app.get("/conversations/{thread_id}/history")
def history(thread_id: str, user: Auth):
    with transaction() as db:
        owned(db, Conversation, thread_id, user.id)
        return {
            "messages": [
                serialize(m)
                for m in db.scalars(
                    select(Message)
                    .where(Message.conversation_id == thread_id)
                    .order_by(Message.created_at)
                )
            ],
            "runs": [
                serialize(r)
                for r in db.scalars(
                    select(Run).where(Run.conversation_id == thread_id).order_by(Run.created_at)
                )
            ],
            "proposals": [
                serialize(p)
                for p in db.scalars(
                    select(Proposal)
                    .where(Proposal.conversation_id == thread_id)
                    .order_by(Proposal.created_at)
                )
            ],
        }


@app.post("/conversations/{thread_id}/runs", status_code=202)
def start_run(thread_id: str, payload: RunInput, user: Auth):
    if not settings.provider_key:
        raise HTTPException(
            503,
            f"Add {settings.key_name} directly to .env and restart API and worker. Non-AI features are available.",
        )
    limit("run:" + user.id, 15)
    try:
        with transaction() as db:
            db.execute(select(User).where(User.id == user.id).with_for_update())
            conversation = owned(db, Conversation, thread_id, user.id, lock=True)
            if conversation.project_id:
                owned(db, Project, conversation.project_id, user.id)
            for doc_id in payload.document_ids:
                doc = owned(db, Document, doc_id, user.id)
                if conversation.project_id and doc.project_id != conversation.project_id:
                    raise HTTPException(422, "Selected document belongs to a different project.")
                if doc.status != "ready":
                    raise HTTPException(409, "Wait for selected documents to finish indexing.")
            active_count = db.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.user_id == user.id, Run.status.in_(["queued", "running"]))
            )
            if active_count >= 3:
                raise HTTPException(429, "At most three active runs per account.")
            run = Run(user_id=user.id, conversation_id=thread_id, input=payload.model_dump())
            db.add(run)
            db.flush()
            db.add(
                Message(
                    user_id=user.id,
                    conversation_id=thread_id,
                    run_id=run.id,
                    role="user",
                    content=payload.message,
                )
            )
            if conversation.title == "New conversation":
                conversation.title = payload.message[:80]
            conversation.version += 1
            result = serialize(run)
    except IntegrityError:
        raise HTTPException(
            409, "This conversation already has an active run or pending approval."
        ) from None
    return result


@app.get("/runs/{run_id}")
def get_run(run_id: str, user: Auth):
    with transaction() as db:
        return serialize(owned(db, Run, run_id, user.id))


@app.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user: Auth):
    with transaction() as db:
        run = owned(db, Run, run_id, user.id, lock=True)
        if run.status in {"queued", "running", "waiting"}:
            run.cancel_requested = True
            for proposal in db.scalars(
                select(Proposal).where(
                    Proposal.run_id == run.id, Proposal.status.in_(["pending", "approved"])
                )
            ):
                proposal.status = "stale"
            if run.status != "running":
                run.status = "canceled"
            result = serialize(run)
        else:
            result = serialize(run)
    emit(run_id, "run.canceled", {"requested": True})
    return result


@app.get("/runs/{run_id}/events")
async def stream(run_id: str, user: Auth, request: Request, cursor: int = Query(0, ge=0)):
    with transaction() as db:
        owned(db, Run, run_id, user.id)

    async def events():
        last, heartbeat = cursor, 0
        while not await request.is_disconnected():
            with transaction() as db:
                run = db.scalar(select(Run).where(Run.id == run_id, Run.user_id == user.id))
                if run is None:
                    # Ownership was checked before headers. A later deletion is
                    # normal stream termination, not a new HTTP response.
                    return
                rows = list(
                    db.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.seq > last)
                        .order_by(RunEvent.seq)
                        .limit(100)
                    )
                )
                status, thread_id = run.status, run.conversation_id
            for event in rows:
                envelope = {
                    "id": event.seq,
                    "seq": event.seq,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "type": event.type,
                    "payload": event.payload,
                }
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(envelope)}\n\n"
                last = event.seq
            if not rows and status in {"completed", "failed", "canceled", "waiting"}:
                break
            heartbeat += 1
            if heartbeat % 30 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, user: Auth):
    with transaction() as db:
        return serialize(owned(db, Proposal, proposal_id, user.id))


@app.post("/proposals/{proposal_id}/decision")
def proposal_decision(proposal_id: str, payload: Decision, user: Auth):
    return decide(user.id, proposal_id, payload)


@app.get("/documents")
def list_documents(
    user: Auth,
    project_id: str | None = None,
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    with transaction() as db:
        query = select(Document).where(
            Document.user_id == user.id, Document.filename.ilike(f"%{q[:200]}%")
        )
        if project_id:
            owned(db, Project, project_id, user.id)
            query = query.where(Document.project_id == project_id)
        return [
            serialize(d)
            for d in db.scalars(
                query.order_by(Document.created_at.desc(), Document.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ]


@app.post("/documents", status_code=202)
async def upload_document(
    user: Auth,
    file: Annotated[UploadFile, File()],
    project_id: Annotated[str | None, Form()] = None,
):
    limit("upload:" + user.id, 10)
    return await documents.upload(file, user.id, project_id)


@app.post("/documents/{document_id}/retry")
def retry_document(document_id: str, user: Auth):
    with transaction() as db:
        document = owned(db, Document, document_id, user.id, lock=True)
        if document.status not in {"failed", "ready"}:
            raise HTTPException(409, "Only failed or ready documents can be reindexed.")
        job = db.scalar(
            select(IngestionJob).where(IngestionJob.document_id == document_id).with_for_update()
        )
        document.status, document.error = "queued", None
        job.status, job.attempts, job.lease_until = "queued", 0, None
        return serialize(document)


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, version: int, user: Auth):
    with transaction() as db:
        doc = owned(db, Document, document_id, user.id, lock=True)
        check_version(doc, version)
        blob = doc.blob
        db.delete(doc)
    (settings.blobs / blob).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/documents/{document_id}/preview")
def preview(document_id: str, user: Auth, download: bool = False):
    with transaction() as db:
        doc = owned(db, Document, document_id, user.id)
        if doc.media_type != "application/pdf":
            raise HTTPException(415, "Use source excerpts for this format.")
        if not (settings.blobs / doc.blob).is_file():
            raise HTTPException(
                404,
                "Original file unavailable. Restore document storage or upload the document again.",
            )
        return FileResponse(
            settings.blobs / doc.blob,
            media_type="application/pdf",
            filename=doc.filename,
            content_disposition_type="attachment" if download else "inline",
            headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"},
        )


@app.get("/sources/{source_id}")
def source(source_id: str, user: Auth):
    with transaction() as db:
        chunk = owned(db, Chunk, source_id, user.id)
        doc = owned(db, Document, chunk.document_id, user.id)
        return {
            "id": chunk.id,
            "document_id": doc.id,
            "filename": doc.filename,
            "page": chunk.page,
            "section": chunk.section,
            "excerpt": chunk.content,
            "media_type": doc.media_type,
        }


@app.get("/memories")
async def memories(request: Request, user: Auth, q: str = ""):
    return [
        m
        for m in await list_memories(request.app.state.store, user.id)
        if q.lower() in (m["title"] + m["content"]).lower()
    ]


@app.post("/memories")
async def create_memory(payload: MemoryInput, request: Request, user: Auth):
    with transaction() as db:
        db.execute(select(User).where(User.id == user.id).with_for_update())
        if payload.project_id:
            owned(db, Project, payload.project_id, user.id, lock=True)
        return await save_memory(TransactionalStore(db), user.id, payload)


@app.put("/memories/{memory_id}")
async def edit_memory(memory_id: str, payload: MemoryInput, request: Request, user: Auth):
    with transaction() as db:
        db.execute(select(User).where(User.id == user.id).with_for_update())
        if payload.project_id:
            owned(db, Project, payload.project_id, user.id, lock=True)
        return await save_memory(TransactionalStore(db), user.id, payload, memory_id)


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, version: int, request: Request, user: Auth):
    with transaction() as db:
        db.execute(select(User).where(User.id == user.id).with_for_update())
        await delete_memory_record(TransactionalStore(db), user.id, memory_id, version)
    return {"ok": True}


@app.post("/memories/clear")
async def clear_memories(request: Request, user: Auth):
    with transaction() as db:
        db.execute(select(User).where(User.id == user.id).with_for_update())
        store = TransactionalStore(db)
        for item in await list_memories(store, user.id):
            await store.adelete(namespace(user.id, item.get("project_id")), item["id"])
    return {"ok": True}
