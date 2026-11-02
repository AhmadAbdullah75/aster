"""Portable, non-overwriting secret generation (never prints secrets)."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if not target.exists():
    content = (root / ".env.example").read_text()
    content = content.replace("GENERATE_LOCAL_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_RANDOM_SECRET", secrets.token_hex(48))
    with target.open("x") as file:
        file.write(content)
    print("Created .env with local credentials; provider key remains empty.")
