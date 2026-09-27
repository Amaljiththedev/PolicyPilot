"""Slack bot (Phase 11): answers in threads with citations, escalates by tagging a person,
and turns 👍/👎 reactions on its answers into feedback.

The logic here is plain functions (easy to test). scripts/slack_bot.py connects them to Slack
over Socket Mode, which needs no public URL, so it works before the app is deployed.
"""
import re

from sqlalchemy.orm import Session

from app.api.services.answer import answer_question
from app.api.services.query_log import log_query
from app.core.config import get_settings
from app.db.models import Feedback, Query

MENTION = re.compile(r"<@[A-Z0-9]+>")
POSITIVE = {"+1", "thumbsup", "white_check_mark", "heavy_check_mark", "raised_hands"}
NEGATIVE = {"-1", "thumbsdown", "x", "no_entry"}


def question_from_event(event: dict) -> str | None:
    """Text to answer, or None for events the bot must ignore (its own posts, edits, joins)."""
    if event.get("bot_id") or event.get("subtype"):
        return None
    if event.get("type") == "message" and event.get("channel_type") != "im":
        return None                       # in channels, only answer when mentioned
    text = MENTION.sub("", event.get("text") or "").strip()
    return text or None


def format_reply(result: dict) -> str:
    s = get_settings()
    if not result["answerable"]:
        msg = f"{result['answer']}"
        if s.SLACK_ESCALATION_USER_ID:
            msg += f"\n<@{s.SLACK_ESCALATION_USER_ID}> could you help with this one?"
        return msg
    cited = [src for src in result["sources"] if src["n"] in result["citations"]]
    lines = [result["answer"], "", "*Sources*"]
    for src in cited:
        snippet = " ".join(src["text"].split())[:160]
        lines.append(f"[{src['n']}] _{src['document_title']}_: “{snippet}…”")
    lines.append("\nReact :+1: or :-1: to tell me if this helped.")
    return "\n".join(lines)


def answer_event(db: Session, event: dict) -> dict | None:
    """Answer one Slack event. Returns the result, or None if the event should be ignored."""
    q = question_from_event(event)
    if q is None:
        return None
    return answer_question(db, q, organisation=get_settings().SLACK_DEFAULT_ORGANISATION)


def record_reply(db: Session, result: dict, channel: str, reply_ts: str) -> Query:
    return log_query(db, result, user_id=None, source="slack", slack_channel=channel, slack_ts=reply_ts)


def feedback_from_reaction(db: Session, event: dict) -> Feedback | None:
    """reaction_added on one of the bot's answers -> a Feedback row (+1 / -1)."""
    name = (event.get("reaction") or "").split("::")[0]     # strip skin tone
    rating = 1 if name in POSITIVE else -1 if name in NEGATIVE else None
    item = event.get("item") or {}
    if rating is None or item.get("type") != "message":
        return None
    q = db.query(Query).filter(Query.slack_ts == item.get("ts"),
                               Query.slack_channel == item.get("channel")).first()
    if q is None:
        return None
    fb = Feedback(query_id=q.id, rating=rating, comments=f"slack reaction :{name}: by {event.get('user')}")
    db.add(fb)
    db.commit()
    return fb
