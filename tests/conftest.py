"""Shared fixtures: a real-Postgres session inside a transaction that is always rolled back."""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import engine


def pg_up(table: str = "users") -> bool:
    try:
        with engine.connect() as c:
            c.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
def pg():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()
