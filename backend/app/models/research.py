"""A4 research outputs and saved findings (FR-20, FR-21, FR-26; SRS §14.1)."""

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import CreatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base

FINDING_TYPES = ("answer", "comparison", "contradiction", "gap", "review")
CONTRADICTION_LABELS = ("potential_contradiction", "context_dependent")
GAP_SCOPES = ("corpus", "field")


class SavedFinding(Base):
    """An answer, comparison, contradiction, gap, or review the user saved."""

    __tablename__ = "saved_findings"
    __table_args__ = (
        CheckConstraint(one_of("type", FINDING_TYPES), name="type_valid"),
        Index("ix_saved_findings_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[CreatedAt]


class Contradiction(Base):
    """A potential contradiction between findings of two papers, with both passages."""

    __tablename__ = "contradictions"
    __table_args__ = (
        CheckConstraint(one_of("label", CONTRADICTION_LABELS), name="label_valid"),
        Index("ix_contradictions_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    claim_a: Mapped[str] = mapped_column(Text, nullable=False)
    claim_b: Mapped[str] = mapped_column(Text, nullable=False)
    # Snapshots of the cited passages (chunk/document ids, pages, quote), so a deleted
    # document does not break the record.
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    context_note: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[CreatedAt]


class ResearchGap(Base):
    """A potential research gap with the evidence it was found in."""

    __tablename__ = "research_gaps"
    __table_args__ = (
        CheckConstraint(one_of("scope", GAP_SCOPES), name="scope_valid"),
        Index("ix_research_gaps_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[CreatedAt]
