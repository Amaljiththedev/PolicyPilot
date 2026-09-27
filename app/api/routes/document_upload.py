from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.ingestion.parser import CorruptDocument, EmptyDocument, UnsupportedFileType
from app.api.services.embeddings import EmbeddingError
from app.api.services.ingest import DuplicateDocument, NoChunks, ingest_bytes
from app.api.services.versioning import diff_texts
from app.db.models import Document, User
from app.schemas.document import ChangesRead, DocumentRead

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(                      # plain def: embedding is CPU-heavy, runs in threadpool
    file: UploadFile = File(...),
    policy_key: str | None = Form(None, description="Same key as an existing policy = upload a new version of it"),
    organisation: str | None = Form(None, description="Who this policy belongs to, e.g. 'Faversham Town Council'"),
    effective_date: date | None = Form(None, description="When this version takes effect (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = file.file.read()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 20 MB)")
    try:
        return ingest_bytes(db, content, file.filename, file.content_type, current_user.id,
                            policy_key=policy_key, organisation=organisation,
                            effective_date=effective_date)
    except DuplicateDocument as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except UnsupportedFileType as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))
    except (EmptyDocument, CorruptDocument, NoChunks) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except EmbeddingError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"embedding failed: {e}")


@router.get("", response_model=list[DocumentRead])
def list_documents(include_superseded: bool = False, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    q = db.query(Document)
    if not include_superseded:
        q = q.filter(Document.is_current.is_(True))
    return q.order_by(Document.policy_key, Document.version).all()


@router.get("/{document_id}/versions", response_model=list[DocumentRead])
def versions(document_id: int, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return (db.query(Document).filter(Document.policy_key == doc.policy_key)
            .order_by(Document.version).all())


@router.get("/{document_id}/changes", response_model=ChangesRead)
def changes(document_id: int, db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    """What changed between this version and the one it replaced (sentence-level diff, no LLM)."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    if doc.supersedes_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this is the first version; nothing to compare")
    old = db.get(Document, doc.supersedes_id)
    return ChangesRead(document_id=doc.id, version=doc.version, previous_id=old.id,
                       previous_version=old.version, changes=diff_texts(old.raw_text, doc.raw_text))
