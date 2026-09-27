from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=10)


class Source(BaseModel):
    n: int                      # the number used in [n] citations
    chunk_id: int
    document_id: int
    document_title: str
    text: str


class AskResponse(BaseModel):
    query_id: int | None        # use this to send feedback
    question: str
    answer: str
    answerable: bool
    escalate: bool              # true = a person should follow up
    citations: list[int]        # which sources the answer relies on
    sources: list[Source]
    reason: str | None          # why it refused, if it did
    latency_ms: int
    model: str
    prompt_version: str | None = None


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)   # 1 = helpful, -1 = not helpful
    comments: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: int
    query_id: int
    rating: int
