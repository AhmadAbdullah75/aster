"""Read only known synthetic native chats' persisted tool coverage, without provider calls."""

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from langchain_core.messages import ToolMessage  # noqa: E402
from nexus.agent import build_graph  # noqa: E402
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.graph_resources import resources  # noqa: E402
from nexus.models import Conversation, Document, User  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main():
    case, thread_id = sys.argv[1:3]
    assert re.fullmatch(r"[A-Z]+-\d+", case)
    assert not json.loads((ROOT / "artifacts/prepublication/results.json").read_text()).get("halt")
    with transaction() as db:
        user_ids = list(
            db.scalars(
                select(User.id).where(
                    User.email.in_(
                        [
                            "nexus-smoke-publication-20261024a@example.com",
                            "nexus-empty-publication-20261024a@example.com",
                        ]
                    )
                )
            )
        )
        thread = db.get(Conversation, thread_id)
        assert thread and thread.user_id in user_ids
        originals = [
            (settings.blobs / doc.blob).read_bytes()
            for doc in db.scalars(select(Document).where(Document.user_id == thread.user_id))
            if doc.media_type
            in {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
            and (settings.blobs / doc.blob).is_file()
        ]
    async with resources() as (saver, store):
        snapshot = await build_graph(saver, store).aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
    evidence = []
    for message in snapshot.values.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue
        try:
            result = json.loads(message.content)
        except (TypeError, ValueError):
            continue
        if "covered_chunks" not in result:
            continue
        evidence.append(
            {
                key: result.get(key)
                for key in (
                    "coverage",
                    "covered_chunks",
                    "total_chunks",
                    "complete",
                    "context_limited",
                    "section_details_omitted",
                    "error",
                )
            }
            | {"source_count": len(result.get("sources", []))}
        )
    serialized = json.dumps(snapshot.values, default=str).encode()
    assert not {"events", "run_events", "file_bytes", "original_bytes", "embeddings"}.intersection(
        snapshot.values
    )
    assert all(original not in serialized for original in originals)
    output = {
        "thread_id": thread_id,
        "tool_evidence": evidence,
        "state_keys": sorted(snapshot.values),
        "decoded_state_json_bytes": len(serialized),
        "binary_originals_checked": len(originals),
        "binary_originals_or_event_log_in_state": False,
    }
    (ROOT / f"artifacts/prepublication/{case}-coverage.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps(output))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
