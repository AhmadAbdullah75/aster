"""Synthetic high-volume history for browser pagination regression, isolated e2e DB only."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
url = str(dotenv_values(root / ".env")["DATABASE_URL"])
os.environ["DATABASE_URL"] = url.rsplit("/", 1)[0] + "/nexus_e2e"
sys.path.insert(0, str(root / "apps" / "api"))

from nexus.db import transaction  # noqa: E402
from nexus.models import Conversation, Message, Run, User  # noqa: E402

with transaction() as db:
    user_id = sys.argv[1]
    assert db.get(User, user_id), "An isolated test account is required"
    for number in range(205):
        thread = Conversation(user_id=user_id, title=f"Audit history {number:03d}")
        db.add(thread)
        db.flush()
        run = Run(user_id=user_id, conversation_id=thread.id, status="completed", input={})
        db.add(run)
        db.flush()
        db.add(
            Message(
                user_id=user_id,
                conversation_id=thread.id,
                run_id=run.id,
                role="user",
                content=f"Saved audit message {number:03d}",
            )
        )
        db.add(
            Message(
                user_id=user_id,
                conversation_id=thread.id,
                run_id=run.id,
                role="assistant",
                content=f"Saved audit reply {number:03d}",
            )
        )
print("205 synthetic histories created")
