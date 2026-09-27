from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.services.answer import answer_question
from app.api.services.query_log import log_query
from app.db.models import Feedback, Query, User
from app.schemas.ask import AskRequest, AskResponse, FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/ask", tags=["Ask"])


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)):
    if not req.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "question is blank")
    try:
        # a user's own organisation is the default scope, so they don't get another employer's rules
        result = answer_question(db, req.question, req.top_k,
                                 organisation=req.organisation or current_user.organisation)
    except RuntimeError as e:                      # LLM provider down / rate limited
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"answer service unavailable: {e}")

    q = log_query(db, result, current_user.id, source="api")
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
