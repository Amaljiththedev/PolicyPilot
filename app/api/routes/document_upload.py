import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.api.services.chunking import chunk_text
from app.api.services.embeddings import embed_texts, EmbeddingError
from app.db.models import Chunk, Document, User
from app.api.ingestion.parser import (
    extract_text, UnsupportedFileType, EmptyDocument, CorruptDocument,
)
from app.schemas.document import DocumentRead

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(                      # plain def: embedding is CPU-heavy, runs in threadpool
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = file.file.read()

    # 1. cheap checks first
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file too large (max 20 MB)")

    # 2. duplicate check
    file_hash = hashlib.sha256(content).hexdigest()
    existing = db.query(Document).filter(Document.file_hash == file_hash).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"already uploaded as document {existing.id}")

    # 3. parse -> map domain errors to HTTP
    try:
        text = extract_text(content, file.content_type, file.filename)
    except UnsupportedFileType as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))
    except (EmptyDocument, CorruptDocument) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    # 4. chunk + embed
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no chunks produced")
    try:
        vectors = embed_texts(chunks)
        if len(vectors) != len(chunks):
            raise EmbeddingError(f"got {len(vectors)} vectors for {len(chunks)} chunks")
    except EmbeddingError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"embedding failed: {e}")

    # 5. one transaction: document + all chunks, or nothing
    try:
        doc = Document(
            title=file.filename,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            raw_text=text,
            status="ready",
            file_hash=file_hash,
            uploaded_by=current_user.id,
            chunk_count=len(chunks),
        )
        db.add(doc)
        db.flush()  # assigns doc.id without committing

        db.add_all([
            Chunk(document_id=doc.id, chunk_index=i, text=c, embedding=v)
            for i, (c, v) in enumerate(zip(chunks, vectors))
        ])
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(doc)
    return doc
