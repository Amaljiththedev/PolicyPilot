from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.services.embeddings import embed_query
from app.core.config import get_settings
from app.db.models import Chunk, Document

settings = get_settings()


def search_chunks(db: Session, query: str, top_k: int | None = None) -> list[dict]:
    """Return the top-k chunks most similar to the query, most similar first."""
    k = top_k or settings.TOP_K

    # 1. question -> 384-d vector (embed_query adds the BGE query prefix)
    query_embedding = embed_query(query)

    # 2. cosine distance: 0 = same direction, larger = less similar
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")

    # 3. nearest chunks from ready documents only
    stmt = (
        select(Chunk, Document.title, distance)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(distance)
        .limit(k)
    )

    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": title,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "score": round(1 - float(dist), 4),  # distance -> similarity
        }
        for chunk, title, dist in db.execute(stmt).all()
    ]
