from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.services.embeddings import embed_query
from app.api.services.reranker import rerank
from app.core.config import get_settings
from app.db.models import Chunk, Document

settings = get_settings()


def search_chunks(
    db: Session,
    query: str,
    top_k: int | None = None,
    use_rerank: bool | None = None,
    strategy: str | None = None,
) -> list[dict]:
    """Return the top-k chunks most similar to the query, most similar first."""
    k = top_k or settings.TOP_K
    if use_rerank is None:
        use_rerank = settings.RERANK_ENABLED
    strategy = strategy or settings.RERANK_STRATEGY
    candidates = (
        settings.RERANK_CANDIDATES if strategy.startswith("cross") else settings.LLM_RERANK_CANDIDATES
    )
    fetch = max(k, candidates) if use_rerank else k

    query_embedding = embed_query(query)
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(Chunk, Document.title, distance)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(distance)
        .limit(fetch)
    )
    hits = [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": title,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "score": round(1 - float(dist), 4),
        }
        for chunk, title, dist in db.execute(stmt).all()
    ]
    if use_rerank:
        return rerank(query, hits, k, strategy)
    return hits
