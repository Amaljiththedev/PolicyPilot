"""PolicyPilot as an MCP server: lets Claude Desktop, Cursor or any MCP client
search the policies and get cited answers, through the same code path as /ask.

    python -m app.mcp_server          # stdio transport

Everything printed to stdout is protocol, so logs go to stderr.
"""
import logging
import os
import sys

# keep model-loading progress bars out of the logs (stdout must stay pure protocol)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TQDM_DISABLE", "1")

from mcp.server.fastmcp import FastMCP

from app.api.services.answer import answer_question
from app.api.services.query_log import log_query
from app.api.services.retrieval import search_chunks
from app.api.services.versioning import diff_texts
from app.core.config import get_settings
from app.db.models import Document, User
from app.db.session import SessionLocal

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
mcp = FastMCP("PolicyPilot")


def _mcp_user_id(db) -> int:
    email = get_settings().MCP_USER_EMAIL.lower()
    u = db.query(User).filter(User.email == email).first()
    if u is None:
        u = User(email=email, auth_provider="mcp", hashed_password=None, role="staff", is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
    return u.id


@mcp.tool()
def ask_policy(question: str, organisation: str | None = None) -> dict:
    """Answer a question from the organisation's policy documents, with numbered citations.
    Refuses (answerable=false) when the documents don't cover it; never guesses.
    Use `organisation` to restrict to one employer's policies (see list_policies)."""
    db = SessionLocal()
    try:
        r = answer_question(db, question, organisation=organisation)
        q = log_query(db, r, _mcp_user_id(db), source="mcp")
        return {"query_id": q.id, "answer": r["answer"], "answerable": r["answerable"],
                "escalate": r["escalate"], "reason": r["reason"], "quote": r.get("quote"),
                "sources": [{"n": s["n"], "document": s["document_title"], "text": s["text"]}
                            for s in r["sources"] if s["n"] in r["citations"]]}
    finally:
        db.close()


@mcp.tool()
def search_policies(query: str, organisation: str | None = None, top_k: int = 5) -> list[dict]:
    """Return the most relevant passages from current policy documents (no LLM, no answer)."""
    db = SessionLocal()
    try:
        return [{"document": h["document_title"], "document_id": h["document_id"],
                 "score": h["score"], "text": h["text"]}
                for h in search_chunks(db, query, max(1, min(top_k, 10)), organisation=organisation)]
    finally:
        db.close()


@mcp.tool()
def list_policies() -> list[dict]:
    """List current policy documents with their organisation and version."""
    db = SessionLocal()
    try:
        docs = (db.query(Document).filter(Document.is_current.is_(True), Document.status == "ready")
                .order_by(Document.organisation, Document.title).all())
        return [{"document_id": d.id, "title": d.title, "organisation": d.organisation,
                 "version": d.version, "effective_date": str(d.effective_date or "")} for d in docs]
    finally:
        db.close()


@mcp.tool()
def policy_changes(document_id: int) -> dict:
    """What changed in this policy version compared with the version it replaced."""
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return {"error": "document not found"}
        if doc.supersedes_id is None:
            return {"document_id": doc.id, "version": doc.version, "changes": [],
                    "note": "first version; nothing to compare"}
        old = db.get(Document, doc.supersedes_id)
        return {"document_id": doc.id, "version": doc.version, "previous_version": old.version,
                "changes": diff_texts(old.raw_text, doc.raw_text, max_items=30)}
    finally:
        db.close()


def _warm_up():
    """Load the embedding + re-ranker models in the background at start-up, so the first
    real question isn't slowed by model loading (clients time out after ~60 s)."""
    try:
        from app.api.services.embeddings import warm_up
        from app.api.services.reranker import get_cross_encoder
        warm_up()
        s = get_settings()
        if s.RERANK_ENABLED and s.RERANK_STRATEGY.startswith("cross"):
            get_cross_encoder(s.RERANK_MODEL)
    except Exception as e:                      # never let warm-up kill the server
        logging.warning("warm-up failed: %s", e)


if __name__ == "__main__":
    import threading
    threading.Thread(target=_warm_up, daemon=True).start()
    mcp.run()
