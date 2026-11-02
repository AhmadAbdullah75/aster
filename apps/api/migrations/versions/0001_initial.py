"""Initial application schema; graph schemas are migrated separately by their libraries."""

from alembic import op
from nexus.models import Base

revision = "0001"
down_revision = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
