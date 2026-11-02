import uuid
from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    version: Mapped[int] = mapped_column(default=1)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(default="Asia/Karachi")
    memory_enabled: Mapped[bool] = mapped_column(default=True)
    theme: Mapped[str] = mapped_column(default="light")


class Session(Record, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Owned:
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class Project(Record, Owned, Base):
    __tablename__ = "projects"
    deleting: Mapped[bool] = mapped_column(default=False)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")


class InProject:
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )


class Conversation(Record, Owned, InProject, Base):
    __tablename__ = "conversations"
    deleting: Mapped[bool] = mapped_column(default=False)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    archived: Mapped[bool] = mapped_column(default=False)


class Message(Record, Owned, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    interrupted: Mapped[bool] = mapped_column(default=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Run(Record, Owned, Base):
    __tablename__ = "runs"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(default="queued", index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    seq: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index(
            "one_active_run",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running','waiting')"),
        ),
    )


class RunEvent(Record, Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int]
    type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("run_id", "seq"),)


class Document(Record, Owned, InProject, Base):
    __tablename__ = "documents"
    filename: Mapped[str] = mapped_column(String(240))
    blob: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    media_type: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None]
    embedding_dimensions: Mapped[int | None]
    __table_args__ = (UniqueConstraint("user_id", "sha256", "project_id"),)


class Chunk(Record, Owned, Base):
    __tablename__ = "chunks"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    page: Mapped[int | None]
    section: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(1536))
    __table_args__ = (
        Index("chunks_fts", text("to_tsvector('english', content)"), postgresql_using="gin"),
    )


class IngestionJob(Record, Base):
    __tablename__ = "ingestion_jobs"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(default="queued", index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)


class Task(Record, Owned, InProject, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="todo")
    priority: Mapped[str] = mapped_column(default="medium")
    due_date: Mapped[date | None]


class Note(Record, Owned, InProject, Base):
    __tablename__ = "notes"
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")


class Proposal(Record, Owned, Base):
    __tablename__ = "proposals"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str]
    action: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(unique=True)


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str]
    resource_id: Mapped[str | None]
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(primary_key=True)
    window: Mapped[int] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(default=1)
