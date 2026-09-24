from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.api.services.retrieval import search_chunks
from app.db.models import User
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("", response_model=SearchResponse)
def search(
    req: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.query.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "query is blank")
    hits = search_chunks(db, req.query, req.top_k)
    return SearchResponse(query=req.query, hits=hits)
