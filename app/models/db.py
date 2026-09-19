"""SQLAlchemy engine/session setup and ORM models.

Works against both PostgreSQL (production/Docker) and SQLite (local dev, tests) —
see docs/decisions/0001-phase1-stack-choices.md for why.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class ProcessingStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(32))
    file_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="upload")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_status: Mapped[str] = mapped_column(String(32), default=ProcessingStatus.UPLOADED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    upload_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    indexed_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.document_id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(16), default="text")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Structured provenance beyond the searchable text: a table's headers/rows, an
    # image's OCR text/caption/dimensions. See docs/decisions/0004-*.md.
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(32), default="ingest")
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED.value)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """One turn's user question or assistant answer — Phase 12 real persistence,
    replacing Phase 8's in-memory conversation_store.py (see ADR 0008 / ADR 0012)."""

    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("conversations.conversation_id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    # Assistant messages only: chunk_ids of the sources the answer cited, for
    # provenance/audit — see docs/decisions/0012-phase12-conversational-rag.md.
    retrieved_source_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        if settings.database_url.startswith("sqlite"):
            # A SQLite connection is a local file handle, not a network resource —
            # there's no pool worth tuning, and pool_pre_ping/pool_size are
            # meaningless for it (see docs/decisions/0020-phase20-performance.md).
            _engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
        else:
            _engine = create_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                # Sends a lightweight SELECT 1 before handing out a pooled
                # connection, so a connection the DB server silently dropped
                # (idle timeout, restart) gets transparently replaced instead of
                # surfacing as a confusing "server has gone away" error mid-request.
                pool_pre_ping=settings.db_pool_pre_ping,
            )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
