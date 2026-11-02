from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(StrictModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(default="Aster user", min_length=1, max_length=120)


class Profile(StrictModel):
    version: int
    name: str = Field(min_length=1, max_length=120)
    timezone: str
    theme: Literal["light", "dark", "system"] = "light"
    memory_enabled: bool = True

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone, for example Asia/Karachi") from exc
        return value


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    instructions: str = Field(default="", max_length=10000)
    version: int | None = None


class ConversationInput(StrictModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    project_id: str | None = None
    archived: bool = False
    version: int | None = None


class TaskInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    status: Literal["todo", "in_progress", "done"] = "todo"
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: date | None = None
    project_id: str | None = None
    version: int | None = None


class NoteInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100000)
    project_id: str | None = None
    version: int | None = None


class MemoryInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    category: Literal["preference", "profile", "goal", "project_decision"] = "preference"
    enabled: bool = True
    project_id: str | None = None
    version: int | None = None


class RunInput(StrictModel):
    message: str = Field(min_length=1, max_length=40000)
    mode: Literal["auto", "documents", "web"] = "auto"
    document_ids: list[str] = Field(default_factory=list, max_length=30)


ActionName = Literal[
    "tasks.create",
    "tasks.update",
    "tasks.delete",
    "notes.create",
    "notes.update",
    "notes.delete",
    "memories.create",
    "memories.update",
    "memories.delete",
]


class ActionItem(StrictModel):
    id: str | None = None
    version: int | None = None
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    content: str | None = Field(default=None, max_length=100000)
    status: Literal["todo", "in_progress", "done"] | None = None
    priority: Literal["low", "medium", "high"] | None = None
    due_date: date | None = None
    project_id: str | None = None
    category: Literal["preference", "profile", "goal", "project_decision"] | None = None
    enabled: bool | None = None
    include: bool = True


class ActionPayload(StrictModel):
    items: list[ActionItem] = Field(min_length=1, max_length=20)


class Decision(StrictModel):
    approve: bool
    version: int
    payload: ActionPayload | None = None
