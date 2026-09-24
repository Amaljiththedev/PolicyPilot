"""Tests for Phase 5: search / retrieval.

Two layers:
  * Route tests (no database, no model): search_chunks is mocked, auth is overridden.
  * Retrieval tests (real Postgres + pgvector): hand-made vectors, embed_query mocked,
    everything inside a transaction that is rolled back, so your data is untouched.
    Skipped automatically if Postgres isn't running.
"""
import math
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import app
from app.api.deps import get_current_user, get_db
from app.db.models import Chunk, Document, User
from app.db.session import engine
from app.api.services.retrieval import search_chunks

DIM = 384


def axis(i: int) -> list[float]:
    """Unit vector pointing along one axis: easy to reason about cosine similarity."""
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def blend(a: float, b: float) -> list[float]:
    """Mostly axis 0, a little axis 1, normalised."""
    n = math.sqrt(a * a + b * b)
    v = [0.0] * DIM
    v[0], v[1] = a / n, b / n
    return v


# --------------------------------------------------------------------------
# Route tests: HTTP layer only
# --------------------------------------------------------------------------
FAKE_HITS = [
    {"chunk_id": 1, "document_id": 1, "document_title": "Leave Policy",
     "chunk_index": 0, "text": "25 days annual leave", "score": 0.91},
    {"chunk_id": 2, "document_id": 1, "document_title": "Leave Policy",
     "chunk_index": 1, "text": "carry over 5 days", "score": 0.72},
]


@pytest.fixture
def client():
    fake_user = User(id=1, email="t@x.com", hashed_password="x", role="staff", is_active=True)
    old = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


def test_search_returns_hits_in_response_shape(client):
    with patch("app.api.routes.search.search_chunks", return_value=FAKE_HITS):
        r = client.post("/api/v1/search", json={"query": "holiday days", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "holiday days"
    assert [h["chunk_id"] for h in body["hits"]] == [1, 2]
    assert set(body["hits"][0]) == {"chunk_id", "document_id", "document_title",
                                    "chunk_index", "text", "score"}


def test_search_passes_query_and_top_k_to_service(client):
    with patch("app.api.routes.search.search_chunks", return_value=[]) as mock:
        client.post("/api/v1/search", json={"query": "leave", "top_k": 3})
    args = list(mock.call_args.args) + list(mock.call_args.kwargs.values())
    assert "leave" in args and 3 in args


def test_search_blank_query_is_422(client):
    r = client.post("/api/v1/search", json={"query": "   "})
    assert r.status_code == 422


def test_search_empty_query_is_422(client):
    r = client.post("/api/v1/search", json={"query": ""})
    assert r.status_code == 422


def test_search_top_k_out_of_range_is_422(client):
    assert client.post("/api/v1/search", json={"query": "x", "top_k": 0}).status_code == 422
    assert client.post("/api/v1/search", json={"query": "x", "top_k": 51}).status_code == 422


def test_search_without_token_is_401():
    old = dict(app.dependency_overrides)
    app.dependency_overrides.pop(get_current_user, None)
    try:
        r = TestClient(app).post("/api/v1/search", json={"query": "leave"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def test_search_no_results_returns_empty_list(client):
    with patch("app.api.routes.search.search_chunks", return_value=[]):
        r = client.post("/api/v1/search", json={"query": "parking"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


# --------------------------------------------------------------------------
# Retrieval tests: real Postgres + pgvector
# --------------------------------------------------------------------------
def _postgres_up() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM chunks LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _postgres_up(),
                              reason="Postgres not running / tables missing (docker compose up -d)")


@pytest.fixture
def db():
    """Session inside a transaction that is always rolled back."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


def _doc(session, title, status="ready"):
    d = Document(title=title, filename=f"{title}.txt", content_type="text/plain",
                 raw_text="x", status=status, file_hash=f"test-{title}-{status}", chunk_count=1)
    session.add(d)
    session.flush()
    return d


def _chunk(session, doc, idx, txt, vec):
    c = Chunk(document_id=doc.id, chunk_index=idx, text=txt, embedding=vec)
    session.add(c)
    session.flush()
    return c


def _call(session, query, top_k):
    # works whether the signature is (db, query, top_k) or (query, db, top_k)
    try:
        return search_chunks(session, query, top_k)
    except (AttributeError, TypeError):
        return search_chunks(query, session, top_k)


@pytest.fixture
def seeded(db):
    leave = _doc(db, "Leave Policy")
    expenses = _doc(db, "Expenses Policy")
    draft = _doc(db, "Draft Policy", status="processing")
    a = _chunk(db, leave, 0, "25 days paid annual leave", axis(0))
    b = _chunk(db, leave, 1, "carry over up to 5 days", axis(1))
    c = _chunk(db, expenses, 0, "taxi claims after 9pm", axis(2))
    d = _chunk(db, draft, 0, "draft: 30 days leave", axis(0))   # identical vector, not ready
    return db, {"a": a.id, "b": b.id, "c": c.id, "draft": d.id}


@needs_db
def test_results_ordered_by_similarity(seeded):
    db, ids = seeded
    with patch("app.api.services.retrieval.embed_query", return_value=blend(0.9, 0.3)):
        hits = _call(db, "how many holiday days", 3)
    assert [h["chunk_id"] for h in hits] == [ids["a"], ids["b"], ids["c"]]


@needs_db
def test_scores_are_cosine_similarity(seeded):
    db, ids = seeded
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        hits = _call(db, "q", 3)
    by_id = {h["chunk_id"]: h["score"] for h in hits}
    assert by_id[ids["a"]] == pytest.approx(1.0, abs=1e-3)   # same direction
    assert by_id[ids["b"]] == pytest.approx(0.0, abs=1e-3)   # orthogonal
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


@needs_db
def test_top_k_limits_results(seeded):
    db, _ = seeded
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        assert len(_call(db, "q", 1)) == 1
        assert len(_call(db, "q", 2)) == 2


@needs_db
def test_documents_not_ready_are_excluded(seeded):
    db, ids = seeded
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        hits = _call(db, "q", 10)
    assert ids["draft"] not in [h["chunk_id"] for h in hits]


@needs_db
def test_hit_contains_document_title_and_text(seeded):
    db, ids = seeded
    with patch("app.api.services.retrieval.embed_query", return_value=axis(2)):
        top = _call(db, "taxi", 1)[0]
    assert top["chunk_id"] == ids["c"]
    assert top["document_title"] == "Expenses Policy"
    assert top["text"] == "taxi claims after 9pm"
    assert top["chunk_index"] == 0


@needs_db
def test_empty_corpus_returns_empty_list(db):
    db.execute(text("DELETE FROM chunks"))   # rolled back after the test
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        assert _call(db, "q", 5) == []
