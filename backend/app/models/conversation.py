"""Chat history and the trust layer's records: claims, evidence, citations, approvals (FR-25)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import CreatedAt, UpdatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base
from app.models.workspace import KNOWLEDGE_MODES

# A conversation runs in a workspace knowledge mode; a single answer may also use general
# knowledge, which is approved per request and never carried over (SRS §2.3).
MESSAGE_MODES = (*KNOWLEDGE_MODES, "general_knowledge")
MESSAGE_ROLES = ("user", "assistant")
CLAIM_STATUSES = ("supported", "partially_supported", "unsupported", "uncertain")
CITATION_SOURCE_TYPES = ("workspace", "external", "general")


class Conversation(Base):
    """A workspace-scoped chat thread."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(one_of("mode", KNOWLEDGE_MODES), name="mode_valid"),
        Index("ix_conversations_workspace_id_updated_at", "workspace_id", "updated_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text)
    # Starting in corpus_web is logged as an approval for the conversation (SRS §2.3, D-014).
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[CreatedAt]
    # Bumped with every new message, so recent conversations list first.
    updated_at: Mapped[UpdatedAt]


class Message(Base):
    """A user question or an assistant answer, stored with its knowledge mode."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(one_of("role", MESSAGE_ROLES), name="role_valid"),
        CheckConstraint(one_of("mode", MESSAGE_MODES), name="mode_valid"),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    # clock_timestamp, not now(): messages saved in one transaction must still sort in insert order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    claims: Mapped[list["Claim"]] = relationship(
        order_by="Claim.position", cascade="all, delete-orphan", lazy="raise"
    )


class Claim(Base):
    """A claim extracted from an answer, with its verification status (FR-12, SRS §12.2)."""

    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(one_of("status", CLAIM_STATUSES), name="status_valid"),
        UniqueConstraint("message_id", "position"),
    )

    id: Mapped[UUIDPrimaryKey]
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    # Order of the claim within the answer.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    support_score: Mapped[float | None] = mapped_column(Float)

    evidence: Mapped[list["Evidence"]] = relationship(
        cascade="all, delete-orphan", lazy="raise", order_by="Evidence.score.desc()"
    )
    citations: Mapped[list["Citation"]] = relationship(
        cascade="all, delete-orphan", lazy="raise", order_by="Citation.id"
    )


class Evidence(Base):
    """A chunk the verifier judged against a claim."""

    __tablename__ = "evidence"

    id: Mapped[UUIDPrimaryKey]
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null once the chunk's document is deleted; the claim's citations keep a snapshot.
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), index=True
    )
    score: Mapped[float | None] = mapped_column(Float)


class Citation(Base):
    """A source a claim cites, with a snapshot that stays readable after the source is gone."""

    __tablename__ = "citations"
    __table_args__ = (
        CheckConstraint(one_of("source_type", CITATION_SOURCE_TYPES), name="source_type_valid"),
        CheckConstraint(
            "page_start IS NULL OR (page_start >= 1 AND page_end >= page_start)",
            name="page_range_valid",
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Live links for opening the passage (FR-13); set to null when the document is deleted.
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), index=True
    )
    # Snapshot taken when the answer is saved.
    document_title: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)


class Approval(Base):
    """A logged approval request and the user's decision (FR-14, SRS §10.3)."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            f"decision IS NULL OR {one_of('decision', MESSAGE_MODES)}", name="decision_valid"
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    # Null for the conversation-level approval of a corpus_web conversation (D-014).
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    # Why the corpus was insufficient, shown in the approval prompt.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # The knowledge modes offered, e.g. ["corpus_only", "corpus_web", "general_knowledge"].
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # The mode chosen; null while the run waits for the user.
    decision: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]
