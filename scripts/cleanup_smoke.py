"""Remove only the exact synthetic account created by the explicit production smoke."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from nexus.db import transaction  # noqa: E402
from nexus.models import User  # noqa: E402

user_id, email = sys.argv[1:]
assert email.startswith("nexus-smoke-") and email.endswith("@example.com")
with transaction() as db:
    user = db.get(User, user_id)
    assert user and user.email == email
    db.delete(user)
