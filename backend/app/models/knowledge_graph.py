"""Semantic Research Knowledge Graph (FR-33, SRS §9.1, D-081).

Jobs track Generate/Update runs. Extractions and their mentions are per paper and reused across
the owner's workspaces; nodes and edges are per workspace and rebuilt from mentions.
"""

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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import CreatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base

ENTITY_TYPES = ("concept", "method", "dataset", "metric", "task", "tool", "finding")
RELATION_TYPES = ("uses", "evaluated_on", "measured_by", "addresses", "compared_with", "reports")
JOB_KINDS = ("generate", "update")
# queued → running → completed, or failed (SRS §9.1).
JOB_STATUSES = ("queued", "running", "completed", "failed")
ACTIVE_JOB_STATUSES = ("queued", "running")
JOB_PHASES = ("extracting", "building")
EXTRACTION_STATUSES = ("completed", "failed")


class KGJob(Base):
    """One Generate or Update run of a workspace's graph."""

    __tablename__ = "kg_jobs"
    __table_args__ = (
        CheckConstraint(one_of("kind", JOB_KINDS), name="kind_valid"),
        CheckConstraint(one_of("status", JOB_STATUSES), name="status_valid"),
        CheckConstraint(f"phase IS NULL OR {one_of('phase', JOB_PHASES)}", name="phase_valid"),
        Index("ix_kg_jobs_workspace_id_created_at", "workspace_id", "created_at"),
        # At most one queued or running job per workspace, whatever the number of processes.
        Index(
            "uq_kg_jobs_active_workspace_id",
            "workspace_id",
            unique=True,
            postgresql_where=text(one_of("status", ACTIVE_JOB_STATUSES)),
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    phase: Mapped[str | None] = mapped_column(Text)
    documents_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    documents_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    current_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    call_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[CreatedAt]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Written every minute while the job runs; the sweep fails jobs whose heartbeat is stale.
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KGDocumentExtraction(Base):
    """A paper's extraction for one extractor version; the job's checkpoint unit."""

    __tablename__ = "kg_document_extractions"
    __table_args__ = (
        CheckConstraint(one_of("status", EXTRACTION_STATUSES), name="status_valid"),
        UniqueConstraint("document_id", "extractor_version"),
    )

    id: Mapped[UUIDPrimaryKey]
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    chunks_considered: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # Rejections per validation rule; rejected text is never stored.
    rejected_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[CreatedAt]


class KGEntityMention(Base):
    """An entity named in one passage, with the sentence that names it."""

    __tablename__ = "kg_entity_mentions"
    __table_args__ = (CheckConstraint(one_of("entity_type", ENTITY_TYPES), name="type_valid"),)

    id: Mapped[UUIDPrimaryKey]
    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_document_extractions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    surface_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)


class KGRelationMention(Base):
    """A relationship one passage states between two of its entity mentions."""

    __tablename__ = "kg_relation_mentions"
    __table_args__ = (
        CheckConstraint(one_of("relation_type", RELATION_TYPES), name="type_valid"),
        CheckConstraint("source_mention_id <> target_mention_id", name="not_self"),
    )

    id: Mapped[UUIDPrimaryKey]
    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_document_extractions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_mention_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_entity_mentions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_mention_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_entity_mentions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    entailment_score: Mapped[float] = mapped_column(Float, nullable=False)


class KGGraph(Base):
    """The workspace's current graph and the papers it was built from."""

    __tablename__ = "kg_graphs"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    built_by_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("kg_jobs.id", ondelete="SET NULL")
    )
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Hash of the extractor version and the sorted ids of the papers built from.
    source_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)


class KGNode(Base):
    """An entity of the workspace graph, merged from mentions of equal type and name."""

    __tablename__ = "kg_nodes"
    __table_args__ = (
        CheckConstraint(one_of("entity_type", ENTITY_TYPES), name="type_valid"),
        UniqueConstraint("workspace_id", "entity_type", "normalized_key"),
    )

    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)


class KGEdge(Base):
    """A relationship type between two nodes, supported by one or more relation mentions."""

    __tablename__ = "kg_edges"
    __table_args__ = (
        CheckConstraint(one_of("relation_type", RELATION_TYPES), name="type_valid"),
        UniqueConstraint(
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            name="uq_kg_edges_endpoints_relation_type",
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    source_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)


class KGNodeMention(Base):
    """An entity mention supporting a node."""

    __tablename__ = "kg_node_mentions"

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    mention_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_entity_mentions.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class KGEdgeMention(Base):
    """A relation mention supporting an edge."""

    __tablename__ = "kg_edge_mentions"

    edge_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_edges.id", ondelete="CASCADE"), primary_key=True
    )
    relation_mention_id: Mapped[UUID] = mapped_column(
        ForeignKey("kg_relation_mentions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
