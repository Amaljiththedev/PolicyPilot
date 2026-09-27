"""First-stage retrieval: vector, keyword, or hybrid (both fused with RRF).

    vector   pgvector cosine distance on bge-small embeddings (meaning)
    keyword  Postgres full-text search, ranked with ts_rank_cd (exact words)
    hybrid   run both, fuse their ranks with RRF (k=60)

An optional re-ranker then re-orders the candidates (see reranker.py).
"""
from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from app.api.services.embeddings import embed_query
from app.api.services.reranker import rerank
from app.core.config import get_settings
from app.db.models import Chunk, Document

settings = get_settings()
MODES = ("vector", "keyword", "hybrid")
RRF_K = 60


def rrf_merge(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    """Fuse several ranked lists of ids. score(id) = sum of 1/(k + rank) over the lists it appears in."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda cid: scores[cid], reverse=True)


def _or_query(query: str):
    """Match ANY query word (not all), otherwise long questions almost never match.
    plainto_tsquery stems and drops stop-words, giving 'a' & 'b'; swap & for |."""
    return func.to_tsquery("english", func.replace(
        cast(func.plainto_tsquery("english", query), Text), "&", "|"))


def _scope(stmt, scope):
    """Only ready documents; by default only the current version of each policy;
    optionally only one organisation's policies."""
    stmt = stmt.where(Document.status == "ready")
    if not scope.get("include_superseded"):
        stmt = stmt.where(Document.is_current.is_(True))
    if scope.get("organisation"):
        stmt = stmt.where(Document.organisation == scope["organisation"])
    return stmt


def _vector_rows(db, qvec, limit, scope):
    distance = Chunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (select(Chunk, Document.title, distance)
            .join(Document, Chunk.document_id == Document.id))
    stmt = _scope(stmt, scope).order_by(distance).limit(limit)
    return db.execute(stmt).all()


def _keyword_rows(db, query, qvec, limit, scope):
    tsv = func.to_tsvector("english", Chunk.text)
    tsq = _or_query(query)
    rank = func.ts_rank_cd(tsv, tsq).label("kw_rank")
    distance = Chunk.embedding.cosine_distance(qvec).label("distance")
    stmt = (select(Chunk, Document.title, distance)
            .join(Document, Chunk.document_id == Document.id)
            .where(tsv.op("@@")(tsq)))
    stmt = _scope(stmt, scope).order_by(rank.desc()).limit(limit)
    return db.execute(stmt).all()


def _to_hit(chunk, title, dist) -> dict:
    return {"chunk_id": chunk.id, "document_id": chunk.document_id, "document_title": title,
            "chunk_index": chunk.chunk_index, "text": chunk.text,
            "score": round(1 - float(dist), 4)}


def search_chunks(db: Session, query: str, top_k: int | None = None,
                  use_rerank: bool | None = None, strategy: str | None = None,
                  mode: str | None = None, include_superseded: bool = False,
                  organisation: str | None = None) -> list[dict]:
    """Return the top-k chunks for the query, best first.
    Superseded policy versions are excluded unless include_superseded=True."""
    scope = {"include_superseded": include_superseded, "organisation": organisation}
    k = top_k or settings.TOP_K
    mode = mode or settings.SEARCH_MODE
    if mode not in MODES:
        raise ValueError(f"unknown search mode {mode!r}, use one of {MODES}")
    if use_rerank is None:
        use_rerank = settings.RERANK_ENABLED
    strategy = strategy or settings.RERANK_STRATEGY
    candidates = (settings.RERANK_CANDIDATES if strategy.startswith("cross")
                  else settings.LLM_RERANK_CANDIDATES)
    fetch = max(k, candidates) if use_rerank else k

    qvec = embed_query(query)
    if mode == "vector":
        hits = [_to_hit(*r) for r in _vector_rows(db, qvec, fetch, scope)]
    elif mode == "keyword":
        hits = [_to_hit(*r) for r in _keyword_rows(db, query, qvec, fetch, scope)]
    else:
        pool = max(fetch, settings.HYBRID_CANDIDATES)
        vec = {r[0].id: r for r in _vector_rows(db, qvec, pool, scope)}
        kw = {r[0].id: r for r in _keyword_rows(db, query, qvec, pool, scope)}
        rows = {**vec, **kw}
        vrank = {cid: i for i, cid in enumerate(vec, 1)}
        krank = {cid: i for i, cid in enumerate(kw, 1)}
        hits = []
        for cid in rrf_merge([list(vec), list(kw)])[:fetch]:
            h = _to_hit(*rows[cid])
            h["vector_rank"], h["keyword_rank"] = vrank.get(cid), krank.get(cid)
            hits.append(h)

    if use_rerank:
        return rerank(query, hits, k, strategy)
    return hits
