from alembic import context
from nexus.config import settings
from nexus.models import Base
from sqlalchemy import create_engine

with create_engine(settings.database_url).connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
