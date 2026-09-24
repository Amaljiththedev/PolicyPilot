from pydantic import BaseModel, Field

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchHit(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    chunk_index: int
    text: str
    score: float  # cosine similarity: 1 = identical meaning


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]