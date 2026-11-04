import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import database


def test_sqlite_session_commit_and_rollback(tmp_path, monkeypatch):
    engine = database.create_database_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE entries (id INTEGER PRIMARY KEY)"))
        dependency = database.get_db()
        session = next(dependency)
        session.execute(text("INSERT INTO entries (id) VALUES (1)"))
        session.commit()
        with pytest.raises(StopIteration):
            next(dependency)

        dependency = database.get_db()
        session = next(dependency)
        session.execute(text("INSERT INTO entries (id) VALUES (2)"))
        with pytest.raises(RuntimeError, match="abort"):
            dependency.throw(RuntimeError("abort"))

        with Session(engine) as verification:
            assert verification.execute(text("SELECT id FROM entries")).scalars().all() == [1]
    finally:
        engine.dispose()
