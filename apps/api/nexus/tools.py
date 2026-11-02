import ast
import math
import operator
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from sqlalchemy import or_, select

from .db import transaction
from .models import Note, Task
from .schemas import ActionName, ActionPayload
from .services import serialize

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def default_project_for_creation(action: str, payload: dict, project_id: str | None, query: str):
    """Apply conversation scope before review, rather than relying on model metadata.

    Only new tasks/notes inherit scope. Existing items and general memories keep
    their own scope. Clear personal-workspace requests are an explicit override;
    the query is the user's message, never retrieved document instructions.
    """
    if not project_id or action not in {"tasks.create", "notes.create"}:
        return payload
    personal = bool(
        re.search(
            r"\b(?:create|add|save|propose|make|need|want)\s+(?:(?:a|an|one|two|three|four|\d+)\s+)?(?:new\s+)?personal\s+(?:tasks?|notes?)\b"
            r"|\b(?:in|to|for)\s+(?:my|the)\s+personal\s+(?:workspace|space|list)\b"
            r"|\b(?:outside|not\s+(?:in|under|linked\s+to))\s+(?:of\s+)?(?:this|the|any)\s+project\b",
            query,
            re.I,
        )
    )
    return {
        **payload,
        "items": [
            {**item, "project_id": None if personal else item.get("project_id") or project_id}
            if isinstance(item, dict)
            else item
            for item in payload.get("items", [])
        ],
    }


def requested_planning_window(query: str, timezone: str):
    """Recognize explicit bounded planning requests, using the user's local date."""
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "thirty": 30,
    }
    number = r"\d{1,3}|" + "|".join(words)
    matches = re.findall(
        rf"\bnext\s+({number})\s+(?:local\s+)?(?:calendar\s+)?(days?|weeks?)\b", query, re.I
    )
    if not matches:
        matches = re.findall(rf"\b({number})[- ](days?|weeks?)[- ](?:plan|schedule)\b", query, re.I)
    if len(matches) != 1:
        return None
    count, unit = matches[0]
    days = (int(count) if count.isdigit() else words[count.lower()]) * (
        7 if unit.lower().startswith("week") else 1
    )
    if not 1 <= days <= 366:
        return None
    today = datetime.now(ZoneInfo(timezone)).date()
    return today, today + timedelta(days=days)


def validate_planning_dates(query: str, items: list, timezone: str):
    window = requested_planning_window(query, timezone)
    if not window:
        return
    start, end = window
    for item in items:
        try:
            due = date.fromisoformat(str(item.get("due_date", "")))
        except ValueError:
            due = None
        if due is None or not start <= due <= end:
            raise ValueError(
                f"The requested plan requires every due_date between {start} and {end}, inclusive. Revise the draft dates to this local calendar window; do not copy later document milestones as task deadlines."
            )


def upcoming_weekdays(current: datetime) -> dict[str, str]:
    today = current.date()
    return {
        name: (today + timedelta(days=(index - today.weekday()) % 7 or 7)).isoformat()
        for index, name in enumerate(WEEKDAYS)
    }


def requested_weekday_date(query: str, timezone: str, current: datetime | None = None):
    weekdays = "|".join(WEEKDAYS)
    matches = re.findall(rf"\bnext\s+({weekdays})\b", query, re.I)
    if len(matches) != 1 or len(re.findall(rf"\b(?:{weekdays})\b", query, re.I)) != 1:
        return None
    # Explicit dates and multi-weekday requests need the full conversational interpretation.
    if re.search(
        r"\b\d{4}-\d{2}-\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
        query,
        re.I,
    ):
        return None
    current = (current or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    return upcoming_weekdays(current)[matches[0].capitalize()]


def calculate(expression: str) -> float:
    if len(expression) > 200:
        raise ValueError("Expression exceeds 200 characters.")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("Expression too complex.")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result: Any = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("Exponent exceeds safe limit.")
            result = operations[type(node.op)](left, right)
        else:
            raise ValueError("Only numbers, parentheses and arithmetic operators are allowed.")
        if isinstance(result, complex) or not math.isfinite(result) or abs(result) > 1e100:
            raise ValueError("Result exceeds safe bounds.")
        return result

    return visit(tree.body)


@tool
def search_documents(query: str, coverage: bool = False) -> dict:
    """Search authorized selected documents. Use coverage=True for whole-document summaries; report incomplete coverage."""
    raise RuntimeError("Executed by authorized runtime")


@tool
def web_search(query: str) -> dict:
    """Perform fresh external web search and return provider evidence and real source annotations."""
    raise RuntimeError("Executed by authorized runtime")


@tool
def calculator(expression: str) -> dict:
    """Calculate arithmetic safely, e.g. (120*3)/7. No code execution."""
    return {"result": calculate(expression)}


@tool
def current_datetime() -> dict:
    """Get the current date and time in the user's configured timezone."""
    raise RuntimeError("Executed by authorized runtime")


@tool
def list_tasks(query: str = "") -> dict:
    """List the user's tasks with IDs and versions for authorized updates."""
    raise RuntimeError("Executed by authorized runtime")


@tool
def search_notes(query: str) -> dict:
    """Search and read the user's notes with IDs and versions."""
    raise RuntimeError("Executed by authorized runtime")


@tool
def propose_action(action: ActionName, payload: ActionPayload) -> dict:
    """Propose task/note/memory create/update/delete for human review. No writes occur until approved. Include full fields and ID/version for updates. At most 20 items."""
    raise RuntimeError("Executed by authorized runtime")


TOOLS = [
    search_documents,
    web_search,
    calculator,
    current_datetime,
    list_tasks,
    search_notes,
    propose_action,
]


async def read_tool(name: str, args: dict, context):
    from . import documents, provider

    if name == "calculator":
        return {"result": calculate(args["expression"])}
    if name == "current_datetime":
        current = datetime.now(ZoneInfo(context.timezone))
        return {
            "datetime": current.isoformat(),
            "timezone": context.timezone,
            "upcoming_weekdays": upcoming_weekdays(current),
        }
    if name == "search_documents":
        return await documents.search(
            context.user_id,
            args["query"],
            context.project_id,
            context.document_ids,
            args.get("coverage", False),
        )
    if name == "web_search":
        return await provider.web_search(args["query"])
    if name in {"list_tasks", "search_notes"}:
        model: Any = Task if name == "list_tasks" else Note
        with transaction() as db:
            query = select(model).where(model.user_id == context.user_id)
            if context.project_id:
                query = query.where(model.project_id == context.project_id)
            term = args.get("query", "")[:200]
            if term:
                query = query.where(
                    or_(
                        model.title.ilike(f"%{term}%"),
                        (model.description if model == Task else model.content).ilike(f"%{term}%"),
                    )
                )
            items = [serialize(r) for r in db.scalars(query.limit(10))]
            for item in items:
                for field in ("description", "content"):
                    if item.get(field):
                        item[field] = item[field][:2000]
            return {
                "items": items,
                "notice": "Read results are bounded to ten items and 2000 characters per body.",
            }
    raise ValueError("Unknown read tool")
