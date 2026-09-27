"""Drive sync against a fake Google (httpx.MockTransport) and real Postgres."""
import json
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.crypto import decrypt
from app.db.models import Document, DriveFile, User
from app.integrations import gdrive
from tests.conftest import pg_up

needs_db = pytest.mark.skipif(not pg_up("drive_connections"), reason="Postgres / P10 tables missing")


class FakeDrive:
    """Just enough of the Drive v3 API."""
    def __init__(self):
        self.files = {}      # id -> dict(name, mimeType, modifiedTime, content)

    def put(self, fid, name, mime, modified, content):
        if content.strip():   # the parser rejects near-empty files, so pad real-looking text
            content = content + b" This policy applies to all employees of the council." * 3
        self.files[fid] = dict(id=fid, name=name, mimeType=mime, modifiedTime=modified, content=content)

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith(gdrive.TOKEN_URL):
            assert b"grant_type=refresh_token" in req.content and b"refresh_token=r-tok" in req.content
            return httpx.Response(200, json={"access_token": "a-tok"})
        assert req.headers["authorization"] == "Bearer a-tok"
        if req.url.path == "/drive/v3/files":
            meta = [{k: f[k] for k in ("id", "name", "mimeType", "modifiedTime")} for f in self.files.values()]
            return httpx.Response(200, json={"files": meta})
        fid = req.url.path.split("/")[4]
        return httpx.Response(200, content=self.files[fid]["content"])

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def setup(pg):
    s = get_settings()
    old = s.TOKEN_ENCRYPTION_KEY
    s.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    pg.execute(__import__("sqlalchemy").text("UPDATE documents SET status='hidden_for_test'"))
    u = User(email="drive@example.com", auth_provider="google", role="staff", is_active=True)
    pg.add(u)
    pg.flush()
    conn = gdrive.save_connection(pg, u.id, "drive@example.com", "r-tok")
    conn.folder_id, conn.organisation = "folder1", "Acme"
    fake = FakeDrive()
    with patch("app.api.services.ingest.embed_texts", side_effect=lambda cs: [[0.01] * 384 for _ in cs]):
        yield pg, conn, fake
    s.TOKEN_ENCRYPTION_KEY = old


def docs(db, fid):
    return db.query(Document).filter(Document.policy_key == f"gdrive-{fid}").order_by(Document.version).all()


@needs_db
def test_refresh_token_is_encrypted(setup):
    db, conn, _ = setup
    assert conn.refresh_token_enc != "r-tok" and decrypt(conn.refresh_token_enc) == "r-tok"


@needs_db
def test_first_sync_adds_supported_files_and_skips_others(setup):
    db, conn, fake = setup
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"Annual leave is 25 days.")
    fake.put("f2", "Expenses.txt", "text/plain", "2026-01-01T00:00:00Z", b"Taxis after 9pm are allowed.")
    fake.put("f3", "logo.png", "image/png", "2026-01-01T00:00:00Z", b"\x89PNG")
    r = gdrive.sync_connection(db, conn, fake.client())
    assert sorted(r["added"]) == ["Expenses.txt", "Leave policy"] and r["skipped"] == ["logo.png"]
    d = docs(db, "f1")[0]
    assert (d.organisation, d.version, d.is_current, d.title) == ("Acme", 1, True, "Leave policy")
    assert conn.last_report["added"] and conn.last_synced_at


@needs_db
def test_unchanged_files_are_not_reingested(setup):
    db, conn, fake = setup
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"Annual leave is 25 days.")
    gdrive.sync_connection(db, conn, fake.client())
    r = gdrive.sync_connection(db, conn, fake.client())
    assert r["unchanged"] == 1 and not r["added"] and not r["updated"]
    assert len(docs(db, "f1")) == 1


@needs_db
def test_edited_file_becomes_new_version(setup):
    db, conn, fake = setup
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"Annual leave is 25 days.")
    gdrive.sync_connection(db, conn, fake.client())
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-02-01T00:00:00Z", b"Annual leave is 28 days.")
    r = gdrive.sync_connection(db, conn, fake.client())
    v1, v2 = docs(db, "f1")
    assert r["updated"] == ["Leave policy"]
    assert (v1.is_current, v2.is_current, v2.version, v2.supersedes_id) == (False, True, 2, v1.id)


@needs_db
def test_touched_but_identical_file_is_not_a_new_version(setup):
    db, conn, fake = setup
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"Annual leave is 25 days.")
    gdrive.sync_connection(db, conn, fake.client())
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-03-01T00:00:00Z", b"Annual leave is 25 days.")
    gdrive.sync_connection(db, conn, fake.client())
    assert len(docs(db, "f1")) == 1
    assert db.query(DriveFile).filter_by(file_id="f1").one().modified_time == "2026-03-01T00:00:00Z"


@needs_db
def test_file_removed_from_folder_leaves_search(setup):
    db, conn, fake = setup
    fake.put("f1", "Leave policy", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"Annual leave is 25 days.")
    gdrive.sync_connection(db, conn, fake.client())
    del fake.files["f1"]
    r = gdrive.sync_connection(db, conn, fake.client())
    db.expire_all()
    assert r["removed"] == ["Leave policy"] and docs(db, "f1")[0].status == "removed"


@needs_db
def test_one_bad_file_does_not_stop_sync(setup):
    db, conn, fake = setup
    fake.put("f1", "Empty doc", gdrive.GOOGLE_DOC, "2026-01-01T00:00:00Z", b"   ")
    fake.put("f2", "Good.txt", "text/plain", "2026-01-01T00:00:00Z", b"Real policy text here.")
    r = gdrive.sync_connection(db, conn, fake.client())
    assert r["added"] == ["Good.txt"] and len(r["errors"]) == 1


def test_missing_refresh_token_is_explained():
    with pytest.raises(gdrive.DriveError, match="refresh token"):
        gdrive.save_connection(None, 1, "a@b.com", None)
