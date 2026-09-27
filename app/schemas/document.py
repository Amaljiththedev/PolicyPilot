from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    filename: str
    content_type: str | None
    chunk_count: int
    created_at: datetime
    policy_key: str | None = None
    version: int = 1
    is_current: bool = True
    supersedes_id: int | None = None
    effective_date: date | None = None
    organisation: str | None = None


class Change(BaseModel):
    type: str                 # changed | added | removed
    old: str | None
    new: str | None


class ChangesRead(BaseModel):
    document_id: int
    version: int
    previous_id: int
    previous_version: int
    changes: list[Change]
