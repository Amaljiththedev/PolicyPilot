"""Phase 9: policy versions. Diff logic is pure; versioning + search filtering use real
Postgres inside a rolled-back transaction (skipped if Postgres isn't running)."""
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.services.retrieval import search_chunks
from app.api.services.versioning import attach_version, diff_texts, slugify
from app.db.models import Chunk, Document
from app.db.session import engine

DIM = 384


def axis(i):
    v = [0.0] * DIM
    v[i] = 1.0
    return v


# ---------- pure ----------
def test_slugify():
    assert slugify("Faversham TC Employee Handbook 2024") == "faversham-tc-employee-handbook-2024"
    assert slugify(None) == "untitled"


def test_diff_finds_changed_sentence_and_ignores_line_breaks():
    old = "Requests need 4 weeks notice. You may carry\nforward 5 days."
    new = "Requests need 2 weeks notice. You may carry forward 5 days."
    ch = diff_texts(old, new)
    assert len(ch) == 1 and ch[0]["type"] == "changed"
    assert "4 weeks" in ch[0]["old"] and "2 weeks" in ch[0]["new"]


def test_diff_added_and_removed():
    ch = diff_texts("A. B.", "A. C. B.")
    assert ch == [{"type": "added", "old": None, "new": "C."}]
    assert diff_texts("A. B.", "A.")[0]["type"] == "removed"


# ---------- real Postgres ----------
def _pg_up():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT is_current FROM documents LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _pg_up(), reason="Postgres not running / P9 migration not applied")


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        s.execute(text("UPDATE documents SET status = 'hidden_for_test'"))  # isolate from real docs
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _doc(db, name, txt, vec, key="leave-policy", org=None):
    d = Document(title=name, filename=f"{name}.txt", content_type="text/plain", raw_text=txt,
                 status="ready", file_hash=f"t-{name}", chunk_count=1, organisation=org)
    db.add(d)
    db.flush()
    attach_version(db, d, key)
    db.add(Chunk(document_id=d.id, chunk_index=0, text=txt, embedding=vec))
    db.flush()
    return d


@needs_db
def test_new_version_supersedes_old(db):
    v1 = _doc(db, "v1", "carry forward 5 days", axis(0), org="Acme")
    v2 = _doc(db, "v2", "carry forward 10 days", axis(0))
    assert (v1.is_current, v2.is_current) == (False, True)
    assert (v1.version, v2.version) == (1, 2)
    assert v2.supersedes_id == v1.id
    assert v2.organisation == "Acme"          # inherited from the version it replaces


@needs_db
def test_search_ignores_superseded_versions(db):
    _doc(db, "v1", "carry forward 5 days", axis(0))
    _doc(db, "v2", "carry forward 10 days", axis(0))
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        current = search_chunks(db, "carry over", 5, use_rerank=False, mode="vector")
        everything = search_chunks(db, "carry over", 5, use_rerank=False, mode="vector",
                                   include_superseded=True)
    assert [h["text"] for h in current] == ["carry forward 10 days"]
    assert len(everything) == 2


@needs_db
def test_organisation_filter(db):
    _doc(db, "a", "Acme rule", axis(0), key="a", org="Acme")
    _doc(db, "b", "Beta rule", axis(0), key="b", org="Beta")
    with patch("app.api.services.retrieval.embed_query", return_value=axis(0)):
        hits = search_chunks(db, "rule", 5, use_rerank=False, mode="vector", organisation="Beta")
    assert [h["text"] for h in hits] == ["Beta rule"]


def test_diff_reports_adjacent_edits_separately():
    ch = diff_texts("A 1. B 1. C.", "A 2. B 2. C.")
    assert [c["new"] for c in ch] == ["A 2.", "B 2."]
