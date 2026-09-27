"""Slack bot logic (no Slack connection needed)."""
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.db.models import Feedback, Query
from app.integrations import slack_bot as sb
from tests.conftest import pg_up

needs_db = pytest.mark.skipif(not pg_up("drive_connections"), reason="Postgres / P10 tables missing")

RESULT = {"question": "q", "answer": "Leave is 25 days [1].", "answerable": True, "escalate": False,
          "citations": [1], "reason": None, "latency_ms": 5, "model": "m",
          "sources": [{"n": 1, "chunk_id": 11, "document_id": 1, "document_title": "Leave Policy",
                       "text": "Annual leave is 25 days per year."},
                      {"n": 2, "chunk_id": 12, "document_id": 1, "document_title": "Other", "text": "x"}]}


def test_mention_is_stripped():
    assert sb.question_from_event({"type": "app_mention", "text": "<@U123> how much leave?"}) == "how much leave?"


def test_ignores_bots_edits_and_channel_chatter():
    assert sb.question_from_event({"type": "app_mention", "text": "hi", "bot_id": "B1"}) is None
    assert sb.question_from_event({"type": "message", "subtype": "message_changed", "text": "x"}) is None
    assert sb.question_from_event({"type": "message", "channel_type": "channel", "text": "x"}) is None
    assert sb.question_from_event({"type": "message", "channel_type": "im", "text": "leave?"}) == "leave?"


def test_reply_lists_only_cited_sources():
    text = sb.format_reply(RESULT)
    assert "[1] _Leave Policy_" in text and "Other" not in text and ":+1:" in text


def test_refusal_tags_escalation_contact():
    s = get_settings()
    old = s.SLACK_ESCALATION_USER_ID
    s.SLACK_ESCALATION_USER_ID = "UHR"
    try:
        text = sb.format_reply({**RESULT, "answerable": False, "escalate": True, "answer": "I couldn't find this."})
        assert "<@UHR>" in text and "Sources" not in text
    finally:
        s.SLACK_ESCALATION_USER_ID = old


def test_default_organisation_is_passed_to_answering():
    s = get_settings()
    old = s.SLACK_DEFAULT_ORGANISATION
    s.SLACK_DEFAULT_ORGANISATION = "Acme"
    try:
        with patch.object(sb, "answer_question", return_value=RESULT) as aq:
            sb.answer_event(None, {"type": "app_mention", "text": "<@U1> leave?"})
        assert aq.call_args.kwargs["organisation"] == "Acme"
    finally:
        s.SLACK_DEFAULT_ORGANISATION = old


@needs_db
def test_reaction_becomes_feedback(pg):
    q = sb.record_reply(pg, RESULT, "C1", "1700000000.0001")
    assert (q.source, q.slack_ts) == ("slack", "1700000000.0001")
    fb = sb.feedback_from_reaction(pg, {"reaction": "+1::skin-tone-3", "user": "U9",
                                        "item": {"type": "message", "channel": "C1", "ts": "1700000000.0001"}})
    assert fb.rating == 1 and fb.query_id == q.id
    assert sb.feedback_from_reaction(pg, {"reaction": "-1", "item": {"type": "message", "channel": "C1",
                                                                     "ts": "1700000000.0001"}}).rating == -1


@needs_db
def test_unrelated_reactions_ignored(pg):
    sb.record_reply(pg, RESULT, "C1", "1.1")
    assert sb.feedback_from_reaction(pg, {"reaction": "tada", "item": {"type": "message", "channel": "C1", "ts": "1.1"}}) is None
    assert sb.feedback_from_reaction(pg, {"reaction": "+1", "item": {"type": "message", "channel": "C1", "ts": "9.9"}}) is None
