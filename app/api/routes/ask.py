from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.answer import answer_question
from app.db.models import Feedback, Query, User
from app.schemas.ask import AskRequest, AskResponse, FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/ask", tags=["Ask"])


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "question is blank")
    try:
        result = answer_question(db, req.question, req.top_k)
    except RuntimeError as e:                      # LLM provider down / rate limited
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"answer service unavailable: {e}")

    q = Query(user_id=current_user.id, prompt=req.question, response=result["answer"],
              source_chunk_ids=[s["chunk_id"] for s in result["sources"]],
              cited_chunk_ids=[result["sources"][n - 1]["chunk_id"] for n in result["citations"]],
              answerable=result["answerable"], escalated=result["escalate"],
              refusal_reason=result["reason"], latency_ms=result["latency_ms"],
              model=result["model"])
    db.add(q)
    db.commit()
    db.refresh(q)
    return AskResponse(query_id=q.id, **result)


@router.post("/{query_id}/feedback", response_model=FeedbackResponse,
             status_code=status.HTTP_201_CREATED)
def feedback(query_id: int, req: FeedbackRequest, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    q = db.get(Query, query_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "query not found")
    if q.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your query")
    fb = Feedback(query_id=q.id, rating=req.rating, comments=req.comments)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return FeedbackResponse(id=fb.id, query_id=fb.query_id, rating=fb.rating)
