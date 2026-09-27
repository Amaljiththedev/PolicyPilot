"""One place that records every answered question, whatever channel it came from
(API, Slack, MCP), so feedback and the eval flywheel see all of them."""
from sqlalchemy.orm import Session

from app.db.models import Query


def log_query(db: Session, result: dict, user_id: int | None, source: str = "api",
              slack_channel: str | None = None, slack_ts: str | None = None) -> Query:
    q = Query(user_id=user_id, prompt=result["question"], response=result["answer"],
              source_chunk_ids=[s["chunk_id"] for s in result["sources"]],
              cited_chunk_ids=[result["sources"][n - 1]["chunk_id"] for n in result["citations"]],
              answerable=result["answerable"], escalated=result["escalate"],
              refusal_reason=result["reason"], latency_ms=result["latency_ms"],
              model=result["model"], source=source, slack_channel=slack_channel, slack_ts=slack_ts)
    db.add(q)
    db.commit()
    db.refresh(q)
    return q
