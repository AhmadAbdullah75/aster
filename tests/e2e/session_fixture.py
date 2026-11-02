"""Expire only a named synthetic session in the hard-coded isolated browser database."""

import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
url = str(dotenv_values(root / ".env")["DATABASE_URL"])
os.environ["DATABASE_URL"] = url.rsplit("/", 1)[0] + "/nexus_e2e"
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import Session, User, now  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

email = sys.argv[1]
assert email.startswith("publication-") and email.endswith("@example.com")
with transaction() as db:
    assert db.scalar(text("SELECT current_database()")) == "nexus_e2e"
    user = db.scalar(select(User).where(User.email == email))
    assert user
    for session in db.scalars(select(Session).where(Session.user_id == user.id)):
        session.expires_at = now() - timedelta(seconds=1)
print("Named synthetic sessions expired in nexus_e2e only.")
