"""Durable deletion markers fence new runs and project associations during cleanup."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    # Initial schema metadata may already contain these columns on a clean installation.
    for table in ("projects", "conversations"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS deleting BOOLEAN NOT NULL DEFAULT false"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN deleting SET DEFAULT false")


def downgrade():
    op.drop_column("conversations", "deleting")
    op.drop_column("projects", "deleting")
