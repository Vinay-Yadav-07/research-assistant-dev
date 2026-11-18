"""Workspaces and their document links (SRS §11.1, §14.1)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import CreatedAt, UpdatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base
from app.models.topic_profile import TopicProfile

KNOWLEDGE_MODES = ("corpus_only", "corpus_web")


class Workspace(Base):
    """An isolated research workspace owned by one user."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(one_of("default_mode", KNOWLEDGE_MODES), name="default_mode_valid"),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'corpus_only'")
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    # Loaded with the workspace so the API can show its keyword summary (S7, D-068).
    topic_profile: Mapped[TopicProfile | None] = relationship(lazy="selectin", viewonly=True)

    @property
    def keywords(self) -> list[str] | None:
        """The topic profile's keywords; None until they are generated."""
        return self.topic_profile.keywords if self.topic_profile is not None else None

    @property
    def summary(self) -> str | None:
        """The topic profile's summary; None until it is generated."""
        return self.topic_profile.summary if self.topic_profile is not None else None


class WorkspaceDocument(Base):
    """A document linked to a workspace (many-to-many), with its compatibility check result."""

    __tablename__ = "workspace_documents"
    __table_args__ = (Index("ix_workspace_documents_document_id", "document_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Null when the check was skipped (empty workspace, SRS §11.2).
    compatibility_score: Mapped[float | None] = mapped_column(Float)
    # True when the user chose "Import anyway" after a low-compatibility warning (FR-22).
    override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
