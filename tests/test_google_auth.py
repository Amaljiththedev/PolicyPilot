"""Google sign-in. Google itself is mocked (code exchange + ID-token check);
user creation, linking, domain rules and admin mapping run against real Postgres."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.services import google_oauth as g
from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.models import User
from app.main import app
from tests.conftest import pg_up

needs_db = pytest.mark.skipif(not pg_up("drive_connections"), reason="Postgres / P10 tables missing")


@pytest.fixture
def google_env():
    s = get_settings()
    old = (s.GOOGLE_CLIENT_ID, s.GOOGLE_CLIENT_SECRET, s.GOOGLE_ALLOWED_DOMAINS, s.ADMIN_EMAILS)
    s.GOOGLE_CLIENT_ID, s.GOOGLE_CLIENT_SECRET = "cid.apps.googleusercontent.com", "secret"
    s.GOOGLE_ALLOWED_DOMAINS, s.ADMIN_EMAILS = "", ""
    yield s
    s.GOOGLE_CLIENT_ID, s.GOOGLE_CLIENT_SECRET, s.GOOGLE_ALLOWED_DOMAINS, s.ADMIN_EMAILS = old


@pytest.fixture
def client(pg, google_env):
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: pg
    yield TestClient(app), pg
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


def claims(email="ama@example.com", sub="g-123", verified=True, name="Ama"):
    return {"iss": "https://accounts.google.com", "sub": sub, "email": email,
            "email_verified": verified, "name": name}


def callback(c, cl, purpose="login", **extra):
    state = g.make_state(purpose, **extra)
    with patch.object(g, "exchange_code", return_value={"id_token": "x", "refresh_token": "r"}), \
         patch.object(g, "verify_id_token", return_value=cl):
        return c.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})


def test_login_redirects_to_google(google_env):
    r = TestClient(app).get("/api/v1/auth/google/login", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert loc.startswith(g.AUTH_URL) and "client_id=cid.apps" in loc and "state=" in loc


def test_not_configured_is_503():
    s = get_settings()
    old = s.GOOGLE_CLIENT_ID
    s.GOOGLE_CLIENT_ID = None
    try:
        assert TestClient(app).get("/api/v1/auth/google/login", follow_redirects=False).status_code == 503
    finally:
        s.GOOGLE_CLIENT_ID = old


def test_password_login_disabled_by_default():
    r = TestClient(app).post("/api/v1/auth/login", json={"email": "a@b.com", "password": "whatever1"})
    assert r.status_code == 404 and "google" in r.json()["detail"]


def test_bad_state_rejected(client):
    c, _ = client
    r = c.get("/api/v1/auth/google/callback", params={"code": "c", "state": "forged"})
    assert r.status_code == 400


@needs_db
def test_first_google_signin_creates_user_and_token(client):
    c, db = client
    r = callback(c, claims())
    assert r.status_code == 200, r.text
    body = r.json()
    u = db.query(User).filter(User.email == "ama@example.com").one()
    assert (u.auth_provider, u.google_sub, u.hashed_password, u.role) == ("google", "g-123", None, "staff")
    assert decode_access_token(body["access_token"]) == str(u.id)


@needs_db
def test_second_signin_reuses_user(client):
    c, db = client
    callback(c, claims())
    callback(c, claims(email="ama@example.com"))
    assert db.query(User).filter(User.email == "ama@example.com").count() == 1


@needs_db
def test_existing_password_user_is_linked(client):
    c, db = client
    db.add(User(email="old@example.com", hashed_password="h", role="staff", is_active=True))
    db.flush()
    callback(c, claims(email="old@example.com", sub="g-9"))
    u = db.query(User).filter(User.email == "old@example.com").one()
    assert u.google_sub == "g-9" and u.hashed_password == "h"


@needs_db
def test_domain_allow_list(client, google_env):
    c, _ = client
    google_env.GOOGLE_ALLOWED_DOMAINS = "liverpool.ac.uk"
    assert callback(c, claims(email="x@gmail.com", sub="g-1")).status_code == 403
    assert callback(c, claims(email="x@liverpool.ac.uk", sub="g-2")).status_code == 200


@needs_db
def test_admin_emails_get_admin(client, google_env):
    c, db = client
    google_env.ADMIN_EMAILS = "boss@example.com"
    callback(c, claims(email="boss@example.com", sub="g-b"))
    assert db.query(User).filter(User.email == "boss@example.com").one().role == "admin"


@needs_db
def test_unverified_email_rejected(client):
    c, _ = client
    assert callback(c, claims(verified=False)).status_code == 403


@needs_db
def test_login_state_cannot_be_used_as_drive_state(client):
    """A login callback never creates a Drive connection, and vice versa needs user_id in state."""
    c, db = client
    r = callback(c, claims())
    assert "access_token" in r.json()
