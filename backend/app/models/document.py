"""Uploaded or imported papers (SRS §14.1)."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import CreatedAt, UpdatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base

DOCUMENT_SOURCES = ("upload", "import")
# uploaded → parsing → embedding → ready, or failed (SRS §8.1).
DOCUMENT_STATUSES = ("uploaded", "parsing", "embedding", "ready", "failed")


class Document(Base):
    """A paper owned by one user; linked to workspaces through `workspace_documents`."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(one_of("source", DOCUMENT_SOURCES), name="source_valid"),
        CheckConstraint(one_of("status", DOCUMENT_STATUSES), name="status_valid"),
        # One copy of a file per user; a concurrent second upload hits this (FR-03, D-057).
        UniqueConstraint("user_id", "content_hash"),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'upload'"))
    source_url: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    # SHA-256 of the file bytes.
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'uploaded'"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    # Also marks progress; the startup sweep fails documents stuck in progress (D-049).
    updated_at: Mapped[UpdatedAt]
