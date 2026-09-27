"""Google Drive sync (Phase 10).

A user connects Drive once (OAuth, read-only scope). We keep an encrypted refresh token,
and a sync run then:
  - lists the files in the chosen folder,
  - skips files whose modifiedTime hasn't changed (incremental),
  - ingests new/changed files; a changed file becomes a NEW VERSION of the same policy
    (policy_key = gdrive-<fileId>), so the old text is superseded automatically,
  - marks files removed from the folder as removed (their documents leave search).
Google Docs are exported as plain text; PDF, DOCX, TXT and HTML are downloaded as-is.
HTTP goes through an injectable httpx.Client so tests run without Google.
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.api.services.ingest import DuplicateDocument, ingest_bytes
from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.db.models import Document, DriveConnection, DriveFile

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
GOOGLE_DOC = "application/vnd.google-apps.document"
DOWNLOADABLE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/html": ".html",
}


class DriveError(Exception):
    pass


def save_connection(db: Session, user_id: int, google_email: str | None,
                    refresh_token: str | None) -> DriveConnection:
    if not refresh_token:
        raise DriveError("Google did not return a refresh token; remove PolicyPilot's access at "
                         "myaccount.google.com/permissions and connect again")
    conn = DriveConnection(user_id=user_id, google_email=google_email,
                           refresh_token_enc=encrypt(refresh_token))
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _access_token(conn: DriveConnection, http: httpx.Client) -> str:
    s = get_settings()
    r = http.post(TOKEN_URL, data={"client_id": s.GOOGLE_CLIENT_ID, "client_secret": s.GOOGLE_CLIENT_SECRET,
                                   "refresh_token": decrypt(conn.refresh_token_enc),
                                   "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise DriveError(f"could not refresh Google token: {r.text[:200]}")
    return r.json()["access_token"]


def list_folder(http: httpx.Client, token: str, folder_id: str) -> list[dict]:
    files, page = [], None
    while True:
        params = {"q": f"'{folder_id}' in parents and trashed = false",
                  "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)", "pageSize": 100}
        if page:
            params["pageToken"] = page
        r = http.get(f"{API}/files", params=params, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise DriveError(f"listing folder failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        files += body.get("files", [])
        page = body.get("nextPageToken")
        if not page:
            return files


def download(http: httpx.Client, token: str, f: dict) -> tuple[bytes, str, str]:
    """Returns (content, filename, content_type)."""
    h = {"Authorization": f"Bearer {token}"}
    if f["mimeType"] == GOOGLE_DOC:
        r = http.get(f"{API}/files/{f['id']}/export", params={"mimeType": "text/plain"}, headers=h)
        name, ctype = f"{f['name']}.txt", "text/plain"
    else:
        r = http.get(f"{API}/files/{f['id']}", params={"alt": "media"}, headers=h)
        ext = DOWNLOADABLE[f["mimeType"]]
        name = f["name"] if f["name"].lower().endswith(ext) else f["name"] + ext
        ctype = f["mimeType"]
    if r.status_code != 200:
        raise DriveError(f"download of {f['name']} failed: {r.status_code}")
    return r.content, name, ctype


def sync_connection(db: Session, conn: DriveConnection, http: httpx.Client | None = None) -> dict:
    if not conn.folder_id:
        raise DriveError("no folder chosen for this connection")
    http = http or httpx.Client(timeout=60, follow_redirects=True)
    token = _access_token(conn, http)
    listed = list_folder(http, token, conn.folder_id)
    known = {df.file_id: df for df in db.query(DriveFile).filter(DriveFile.connection_id == conn.id)}
    report = {"added": [], "updated": [], "unchanged": 0, "removed": [], "skipped": [], "errors": []}

    for f in listed:
        if f["mimeType"] != GOOGLE_DOC and f["mimeType"] not in DOWNLOADABLE:
            report["skipped"].append(f["name"])
            continue
        df = known.get(f["id"])
        if df is not None and df.modified_time == f["modifiedTime"] and not df.removed:
            report["unchanged"] += 1
            continue
        try:
            content, name, ctype = download(http, token, f)
            doc = ingest_bytes(db, content, name, ctype, conn.user_id, title=f["name"],
                               policy_key=f"gdrive-{f['id']}", organisation=conn.organisation)
            doc_id = doc.id
        except DuplicateDocument as e:        # touched but identical bytes: nothing new to index
            doc_id = e.existing_id
        except Exception as e:                # one bad file must not stop the whole sync
            report["errors"].append(f"{f['name']}: {e}")
            continue
        if df is None:
            db.add(DriveFile(connection_id=conn.id, file_id=f["id"], name=f["name"],
                             modified_time=f["modifiedTime"], document_id=doc_id))
            report["added"].append(f["name"])
        else:
            df.modified_time, df.document_id, df.name, df.removed = f["modifiedTime"], doc_id, f["name"], False
            report["updated"].append(f["name"])

    present = {f["id"] for f in listed}
    for file_id, df in known.items():
        if file_id not in present and not df.removed:
            df.removed = True
            # every version of that policy leaves search; text stays for audit
            db.query(Document).filter(Document.policy_key == f"gdrive-{file_id}") \
                .update({Document.status: "removed"}, synchronize_session=False)
            report["removed"].append(df.name)

    conn.last_synced_at = datetime.now(timezone.utc)
    conn.last_report = report
    db.commit()
    return report
