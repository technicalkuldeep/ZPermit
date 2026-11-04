"""Reusable synchronous SQLAlchemy session infrastructure.

Callers own transaction boundaries: commit explicitly when a write succeeds.
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    connect_args = (
        {"check_same_thread": False, "timeout": 30}
        if make_url(database_url).get_backend_name() == "sqlite"
        else {}
    )
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


@lru_cache
def get_engine() -> Engine:
    # Lazy initialization avoids opening database resources during module import.
    return create_database_engine(get_settings().database_url)


def get_db() -> Generator[Session, None, None]:
    with Session(get_engine(), expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
