"""Phase 8 tests. No database and no real LLM: search and chat_json are mocked."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.services import answer as ans
from app.api.services.answer import REFUSAL, answer_question, check_citations
from app.db.models import User
from app.main import app

HITS = [
    {"chunk_id": 11, "document_id": 1, "document_title": "Handbook", "chunk_index": 0,
     "text": "A TV licence is needed to watch live TV.", "score": 0.8},
    {"chunk_id": 12, "document_id": 1, "document_title": "Handbook", "chunk_index": 1,
     "text": "The fine can be up to £1,000.", "score": 0.7},
]


def run(llm_out, hits=HITS):
    with patch.object(ans, "search_chunks", return_value=hits), \
         patch.object(ans, "chat_json", return_value=llm_out) as llm:
        return answer_question(None, "do I need a TV licence"), llm


# ---------- citation checking (pure function) ----------
def test_valid_citations_kept():
    text, cites = check_citations("Yes [1]. Fine up to £1,000 [2].", [1, 2], 2)
    assert cites == [1, 2] and "[1]" in text and "[2]" in text


def test_fake_citation_removed_from_text_and_list():
    text, cites = check_citations("Yes [1]. Also [7].", [1, 7], 2)
    assert cites == [1] and "[7]" not in text


def test_citation_only_in_text_still_counts():
    assert check_citations("Yes [2].", [], 2)[1] == [2]


# ---------- answer_question ----------
def test_grounded_answer_returned():
    r, _ = run({"answerable": True, "answer": "Yes, for live TV [1].", "citations": [1]})
    assert r["answerable"] and not r["escalate"] and r["citations"] == [1]
    assert r["answer"] == "Yes, for live TV [1]."


def test_model_says_unanswerable_gives_refusal():
    r, _ = run({"answerable": False, "answer": "", "citations": []})
    assert r["answer"] == REFUSAL and r["escalate"]
    assert r["reason"] == "model_said_unanswerable"


def test_answer_without_valid_citations_is_refused():
    # model claims an answer but cites a passage that doesn't exist
    r, _ = run({"answerable": True, "answer": "Parking is £50 [9].", "citations": [9]})
    assert not r["answerable"] and r["reason"] == "no_valid_citations"


def test_no_passages_skips_llm():
    r, llm = run({}, hits=[])
    assert r["reason"] == "no_passages"
    llm.assert_not_called()


def test_prompt_contains_numbered_passages():
    _, llm = run({"answerable": False})
    prompt = llm.call_args[0][0]
    assert "[1] (Handbook)" in prompt and "[2] (Handbook)" in prompt


# ---------- routes ----------
class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        obj.id = 42

    def get(self, model, id_):
        return None


@pytest.fixture
def client():
    user = User(id=1, email="t@x.com", hashed_password="x", role="staff", is_active=True)
    db = FakeDB()
    old = dict(app.dependency_overrides)      # other test files set overrides at import time
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)      # put them back, don't just wipe them


FAKE_RESULT = {"question": "q", "answer": "Yes [1].", "answerable": True, "escalate": False,
               "citations": [1], "reason": None, "latency_ms": 5, "model": "m",
               "sources": [{"n": 1, "chunk_id": 11, "document_id": 1,
                            "document_title": "Handbook", "text": "t"}]}


def test_ask_route_returns_answer_and_logs_query(client):
    c, db = client
    with patch("app.api.routes.ask.answer_question", return_value=FAKE_RESULT):
        r = c.post("/api/v1/ask", json={"question": "q"})
    assert r.status_code == 200
    body = r.json()
    assert body["query_id"] == 42 and body["citations"] == [1]
    logged = db.added[0]
    assert logged.cited_chunk_ids == [11] and logged.answerable is True


def test_ask_blank_question_is_422(client):
    c, _ = client
    assert c.post("/api/v1/ask", json={"question": "   "}).status_code == 422


def test_ask_llm_down_is_503(client):
    c, _ = client
    with patch("app.api.routes.ask.answer_question", side_effect=RuntimeError("rate limited")):
        assert c.post("/api/v1/ask", json={"question": "q"}).status_code == 503


def test_feedback_unknown_query_is_404(client):
    c, _ = client
    assert c.post("/api/v1/ask/999/feedback", json={"rating": 1}).status_code == 404


def test_ask_without_token_is_401():
    assert TestClient(app).post("/api/v1/ask", json={"question": "q"}).status_code == 401


# ---------- v3: quote first, verified in code ----------
def test_quote_check_matches_across_pdf_line_breaks():
    passage = "Smoking (which includes the use of e-\ncigarettes and personal vaporisers) is prohibited."
    assert ans.quote_in_passages("which includes the use of e-cigarettes and personal vaporisers", [passage])
    assert not ans.quote_in_passages("vaping is allowed in the office", [passage])
    assert not ans.quote_in_passages("is", [passage])          # too short to prove anything


def test_v3_invented_quote_is_refused():
    out = {"answerable": True, "answer": "No note needed [1].", "citations": [1],
           "quote": "You never need a fit note"}
    with patch.object(ans, "search_chunks", return_value=HITS), patch.object(ans, "chat_json", return_value=out):
        r = answer_question(None, "q", prompt_version="v3")
    assert not r["answerable"] and r["reason"] == "quote_not_in_sources"


def test_v3_real_quote_is_answered():
    out = {"answerable": True, "answer": "Yes, for live TV [1].", "citations": [1],
           "quote": "A TV licence is needed to watch live TV."}
    with patch.object(ans, "search_chunks", return_value=HITS), patch.object(ans, "chat_json", return_value=out):
        r = answer_question(None, "q", prompt_version="v3")
    assert r["answerable"] and r["quote"].startswith("A TV licence")


def test_quote_check_tolerates_hyphenation_differences():
    passage = "any absence of more than 4 days to be certified by a 'selfcertification form' (Form SC2)."
    assert ans.quote_in_passages("absence of more than 4 days to be certified by a self-certification form", [passage])


def test_merge_drops_repeated_overlap():
    assert ans._merge("alpha beta gamma delta epsilon zeta eta", "delta epsilon zeta eta theta iota") == \
        "alpha beta gamma delta epsilon zeta eta theta iota"


def test_no_db_means_no_expansion():
    assert ans.expand_with_neighbours(None, HITS, 1) == [h["text"] for h in HITS]
