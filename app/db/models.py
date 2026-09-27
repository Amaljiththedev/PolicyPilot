from sqlalchemy import Index
from datetime import date, datetime, timezone
from typing import Optional, List
from sqlalchemy import String, Text, Integer, Boolean, Date, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.config import get_settings
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # None for Google users
    auth_provider: Mapped[str] = mapped_column(String(32), default="password", nullable=False)
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)
    organisation: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)   # default search scope
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="staff", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    queries: Mapped[List["Query"]] = relationship("Query", back_populates="user")



class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(32), default="processing")  # processing, ready, failed
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Phase 9: versions. All versions of one policy share a policy_key; only one is current.
    policy_key: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    organisation: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)

    chunks: Mapped[List["Chunk"]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(get_settings().EMBEDDING_DIMENSION), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    # Phase 8: what the answer was built from, and whether it was refused
    source_chunk_ids: Mapped[Optional[List[int]]] = mapped_column(JSON, nullable=True)
    cited_chunk_ids: Mapped[Optional[List[int]]] = mapped_column(JSON, nullable=True)
    answerable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refusal_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="api", nullable=False)   # api | slack | mcp
    slack_channel: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    slack_ts: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)  # bot reply ts, for reactions
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="queries")
    feedbacks: Mapped[List["Feedback"]] = relationship("Feedback", back_populates="query", cascade="all, delete-orphan")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    query_id: Mapped[int] = mapped_column(Integer, ForeignKey("queries.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    query: Mapped["Query"] = relationship("Query", back_populates="feedbacks")


class DriveConnection(Base):
    """One user's link to Google Drive: which folder to sync, and an encrypted refresh token."""
    __tablename__ = "drive_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    google_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    folder_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    organisation: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DriveFile(Base):
    """A Drive file we have ingested. modified_time decides whether it needs re-syncing."""
    __tablename__ = "drive_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("drive_connections.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    file_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    modified_time: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("documents.id", ondelete="SET NULL"),
                                                      nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
