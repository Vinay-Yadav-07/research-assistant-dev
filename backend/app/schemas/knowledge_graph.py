"""Knowledge graph API bodies (FR-33, SRS §9.1)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

JobKind = Literal["generate", "update"]
JobStatus = Literal["queued", "running", "completed", "failed"]
JobPhase = Literal["extracting", "building"]
EntityType = Literal["concept", "method", "dataset", "metric", "task", "tool", "finding"]
RelationType = Literal[
    "uses", "evaluated_on", "measured_by", "addresses", "compared_with", "reports"
]
# What the graph page shows (SRS §9.1); derived, never stored.
GraphState = Literal[
    "empty", "queued", "generating", "ready", "update_available", "updating", "failed"
]


class KGJobRead(BaseModel):
    """A Generate or Update run and its real progress: papers read so far, then the build."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    kind: JobKind
    status: JobStatus
    phase: JobPhase | None
    documents_total: int
    documents_done: int
    current_document_id: UUID | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    call_budget: int
    # e.g. `interrupted`, `llm_quota_exhausted`, `budget_exceeded`; papers fully read are kept.
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class KGNodeRead(BaseModel):
    """An entity; counts include only papers currently in the workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: EntityType
    label: str
    aliases: list[str]
    document_count: int
    mention_count: int


class KGEdgeRead(BaseModel):
    """A relationship the papers state between two nodes; counts as for nodes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relation_type: RelationType
    document_count: int
    mention_count: int


class KnowledgeGraphRead(BaseModel):
    """The workspace graph's state; `stale` means its papers changed since it was built.

    `nodes` holds the most-supported nodes (`truncated` when some were left out) and `edges`
    the relationships between them. Evidence of removed papers is never counted or shown.
    """

    state: GraphState
    stale: bool
    ready_documents: int
    built_at: datetime | None
    node_count: int
    edge_count: int
    active_job: KGJobRead | None
    last_job: KGJobRead | None
    nodes: list[KGNodeRead]
    edges: list[KGEdgeRead]
    truncated: bool
