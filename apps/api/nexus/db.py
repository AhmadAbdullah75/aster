from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=8, max_overflow=8)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with SessionLocal.begin() as session:
        yield session
