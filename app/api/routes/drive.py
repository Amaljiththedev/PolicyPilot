from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services import google_oauth as g
from app.core.config import get_settings
from app.db.models import DriveConnection, User
from app.db.session import SessionLocal
from app.integrations.gdrive import DriveError, sync_connection

router = APIRouter(prefix="/drive", tags=["Google Drive"])


def _ready():
    if not g.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured")
    if not get_settings().TOKEN_ENCRYPTION_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TOKEN_ENCRYPTION_KEY is not set")


def _own(db: Session, conn_id: int, user: User) -> DriveConnection:
    conn = db.get(DriveConnection, conn_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found")
    if conn.user_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your connection")
    return conn


def _view(c: DriveConnection) -> dict:
    return {"id": c.id, "google_email": c.google_email, "folder_id": c.folder_id,
            "organisation": c.organisation, "last_synced_at": c.last_synced_at, "last_report": c.last_report}


@router.get("/connect", dependencies=[Depends(_ready)])
def connect(current_user: User = Depends(get_current_user)):
    """Returns a Google consent URL. Open it in a browser; Google sends you back to the callback."""
    return {"auth_url": g.authorization_url("drive", user_id=current_user.id)}


@router.get("/connections")
def connections(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(DriveConnection)
    if current_user.role != "admin":
        q = q.filter(DriveConnection.user_id == current_user.id)
    return [_view(c) for c in q.order_by(DriveConnection.id)]


class FolderIn(BaseModel):
    folder_id: str = Field(description="the ID at the end of the folder's Drive URL")
    organisation: str | None = None


@router.post("/connections/{conn_id}/folder")
def set_folder(conn_id: int, body: FolderIn, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    conn = _own(db, conn_id, current_user)
    conn.folder_id = body.folder_id.strip()
    conn.organisation = body.organisation or current_user.organisation
    db.commit()
    return _view(conn)


def _sync_in_background(conn_id: int):
    db = SessionLocal()
    try:
        conn = db.get(DriveConnection, conn_id)
        try:
            sync_connection(db, conn)
        except DriveError as e:
            conn.last_report = {"error": str(e)}
            db.commit()
    finally:
        db.close()


@router.post("/connections/{conn_id}/sync", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(_ready)])
def sync(conn_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
         current_user: User = Depends(get_current_user)):
    """Starts a sync in the background; check GET /drive/connections for last_report."""
    conn = _own(db, conn_id, current_user)
    if not conn.folder_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "choose a folder first")
    background.add_task(_sync_in_background, conn.id)
    return {"status": "sync started", "connection_id": conn.id}
