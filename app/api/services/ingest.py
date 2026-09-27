"""Shared ingestion: parse -> chunk -> embed -> save document + chunks in one transaction.
Used by the upload route and by scripts, so both follow the same rules."""
import hashlib
from datetime import date

from sqlalchemy.orm import Session

from app.api.ingestion.parser import extract_text
from app.api.ingestion.titles import clean_title
from app.api.services.chunking import chunk_text
from app.api.services.embeddings import EmbeddingError, embed_texts
from app.api.services.versioning import attach_version, slugify
from app.db.models import Chunk, Document


class DuplicateDocument(Exception):
    def __init__(self, existing_id: int):
        super().__init__(f"already uploaded as document {existing_id}")
        self.existing_id = existing_id


class NoChunks(Exception):
    pass


def ingest_bytes(db: Session, content: bytes, filename: str, content_type: str | None,
                 user_id: int | None = None, *, text: str | None = None,
                 title: str | None = None, policy_key: str | None = None,
                 organisation: str | None = None, effective_date: date | None = None) -> Document:
    """Raises: UnsupportedFileType / EmptyDocument / CorruptDocument (parser),
    DuplicateDocument, NoChunks, EmbeddingError. Pass `text` to skip parsing."""
    file_hash = hashlib.sha256(content).hexdigest()
    existing = db.query(Document).filter(Document.file_hash == file_hash).first()
    if existing:
        raise DuplicateDocument(existing.id)

    if text is None:
        text = extract_text(content, content_type, filename)
    chunks = chunk_text(text)
    if not chunks:
        raise NoChunks("no chunks produced")
    vectors = embed_texts(chunks)
    if len(vectors) != len(chunks):
        raise EmbeddingError(f"got {len(vectors)} vectors for {len(chunks)} chunks")

    title = title or clean_title(filename)
    try:
        doc = Document(title=title, filename=filename,
                       content_type=content_type or "application/octet-stream",
                       raw_text=text, status="ready", file_hash=file_hash,
                       uploaded_by=user_id, chunk_count=len(chunks),
                       organisation=organisation, effective_date=effective_date)
        db.add(doc)
        db.flush()
        attach_version(db, doc, slugify(policy_key) if policy_key else slugify(title))
        db.add_all([Chunk(document_id=doc.id, chunk_index=i, text=c, embedding=v)
                    for i, (c, v) in enumerate(zip(chunks, vectors))])
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(doc)
    return doc
