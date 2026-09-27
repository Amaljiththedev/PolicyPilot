"""Auth against REAL Postgres (not SQLite): catches type bugs SQLite hides,
like the JWT "sub" string vs integer users.id that crashed /ask under psycopg 3."""
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.ingestion.titles import clean_title
from app.core.security import create_access_token
from app.db.models import User
from app.db.session import engine


def _pg_up() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM users LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _pg_up(), reason="Postgres not running")


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@needs_db
def test_real_token_resolves_user_in_postgres(db):
    u = User(email="pgtest@example.com", hashed_password="x", role="staff", is_active=True)
    db.add(u)
    db.flush()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(u.id))
    assert get_current_user(creds, db).id == u.id


def test_clean_title():
    assert clean_title("UoL,-,Your,University,2025,(Undergraduate,A5),Online.pdf") == \
        "UoL - Your University 2025 (Undergraduate A5) Online"
    assert clean_title("leave_policy_v2.docx") == "leave policy v2"
    assert clean_title(None) == "untitled"
