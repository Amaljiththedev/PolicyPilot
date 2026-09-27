"""Re-chunk and re-embed an existing document from its stored raw_text.

    python scripts/rechunk.py --document-id 31                      # current CHUNK_SIZE / OVERLAP
    python scripts/rechunk.py --document-id 31 --clean              # strip headers/footers first
    python scripts/rechunk.py --document-id 31 --clean --size 500 --overlap 100

raw_text is never modified, so every chunking experiment starts from the same source
and can be reversed by re-running with other settings. Old chunks are replaced in one
transaction. Eval items match on evidence text, not chunk IDs, so they stay valid.
"""
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.ingestion.cleaning import strip_boilerplate
from app.api.services.chunking import chunk_text
from app.api.services.embeddings import embed_texts
from app.db.models import Chunk, Document
from app.db.session import SessionLocal


def main(document_id: int, clean: bool, size: int | None, overlap: int | None) -> None:
    db = SessionLocal()
    doc = db.get(Document, document_id)
    if doc is None:
        raise SystemExit(f"document {document_id} not found")

    text = doc.raw_text
    if clean:
        text, stats = strip_boilerplate(text)
        print(f"cleaning: {stats}")

    chunks = chunk_text(text, chunk_size=size, overlap=overlap)
    vectors = embed_texts(chunks)
    if len(vectors) != len(chunks):
        raise SystemExit(f"got {len(vectors)} vectors for {len(chunks)} chunks")

    try:
        old = db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
        db.add_all([Chunk(document_id=doc.id, chunk_index=i, text=c, embedding=v,
                          metadata_json={"cleaned": clean, "chunk_size": size, "overlap": overlap})
                    for i, (c, v) in enumerate(zip(chunks, vectors))])
        doc.chunk_count = len(chunks)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"document {document_id}: replaced {old} chunks with {len(chunks)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--document-id", type=int, required=True)
    p.add_argument("--clean", action="store_true", help="strip repeated headers/footers and page numbers")
    p.add_argument("--size", type=int, default=None, help="chunk size (default: CHUNK_SIZE from .env)")
    p.add_argument("--overlap", type=int, default=None, help="chunk overlap (default: CHUNK_OVERLAP)")
    a = p.parse_args()
    main(a.document_id, a.clean, a.size, a.overlap)
