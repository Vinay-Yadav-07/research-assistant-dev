"""Knowledge graph persistence (SRS §9.1, D-081). Every query on user data filters by `user_id`;
workspace reads see only ready documents linked to that user's workspace."""

from collections.abc import AsyncIterator, Callable, Collection
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from sqlalchemy import Select, delete, distinct, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.knowledge_graph import (
    ACTIVE_JOB_STATUSES,
    KGDocumentExtraction,
    KGEdge,
    KGEdgeMention,
    KGEntityMention,
    KGGraph,
    KGJob,
    KGNode,
    KGNodeMention,
    KGRelationMention,
)
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.chunks import ChunkRecord


@dataclass(frozen=True)
class NewEntityMention:
    """An entity mention to store; `key` identifies it within its extraction."""

    key: str
    chunk_id: UUID
    entity_type: str
    surface_text: str
    normalized_key: str
    quote: str


@dataclass(frozen=True)
class NewRelationMention:
    """A relation mention between two entity mentions of the same extraction (by `key`)."""

    chunk_id: UUID
    source_key: str
    target_key: str
    relation_type: str
    quote: str
    entailment_score: float


@dataclass(frozen=True)
class PaperExtraction:
    """What the extractor kept for one paper, and how much it rejected per rule."""

    chunks_considered: int
    entities: list[NewEntityMention] = field(default_factory=list)
    relations: list[NewRelationMention] = field(default_factory=list)
    rejected_counts: dict[str, int] = field(default_factory=dict)
    status: str = "completed"


@dataclass(frozen=True)
class MentionRow:
    """A stored entity mention, as the graph build reads it."""

    id: UUID
    document_id: UUID
    chunk_id: UUID
    entity_type: str
    surface_text: str
    normalized_key: str


@dataclass(frozen=True)
class RelationRow:
    """A stored relation mention, as the graph build reads it."""

    id: UUID
    document_id: UUID
    source_mention_id: UUID
    target_mention_id: UUID
    relation_type: str


@dataclass(frozen=True)
class BuildInputs:
    """Every mention of the papers a graph is built from, and the text of their passages."""

    mentions: list[MentionRow]
    relations: list[RelationRow]
    chunk_texts: dict[UUID, str]


@dataclass(frozen=True)
class NewNode:
    """A node to store with the entity mentions behind it."""

    id: UUID
    entity_type: str
    label: str
    normalized_key: str
    aliases: list[str]
    document_count: int
    mention_ids: list[UUID]


@dataclass(frozen=True)
class NewEdge:
    """An edge to store with the relation mentions behind it."""

    id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relation_type: str
    document_count: int
    relation_mention_ids: list[UUID]


@dataclass(frozen=True)
class NodeView:
    """A node with support counted over the workspace's current papers only."""

    id: UUID
    entity_type: str
    label: str
    aliases: list[str]
    document_count: int
    mention_count: int


@dataclass(frozen=True)
class EdgeView:
    """An edge with support counted over the workspace's current papers only."""

    id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relation_type: str
    document_count: int
    mention_count: int


@dataclass(frozen=True)
class EvidenceRow:
    """One supporting passage of a node or edge: the mention, its paper, pages, and quote."""

    id: UUID
    document_id: UUID
    chunk_id: UUID
    document_title: str | None
    page_start: int
    page_end: int
    section: str | None
    quote: str


@dataclass(frozen=True)
class JobUsage:
    """LLM calls and tokens a job has used so far."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class KnowledgeGraphRepository:
    """Reads and writes one user's knowledge graph jobs and extractions in the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        """True if the workspace exists and belongs to `user_id`."""
        found = await self._session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        return found is not None

    def _ready_in_workspace(self, user_id: UUID, workspace_id: UUID) -> Select[UUID]:
        return (
            select(Document.id)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                Workspace.user_id == user_id,
                Document.user_id == user_id,
                Document.status == "ready",
            )
        )

    async def ready_document_ids(self, user_id: UUID, workspace_id: UUID) -> list[UUID]:
        """Ids of the workspace's ready documents, sorted."""
        rows = await self._session.scalars(
            self._ready_in_workspace(user_id, workspace_id).order_by(Document.id)
        )
        return list(rows)

    async def pending_document_ids(
        self, user_id: UUID, workspace_id: UUID, extractor_version: str
    ) -> list[UUID]:
        """Ready documents of the workspace without a completed extraction of this version,
        in the order they were added."""
        extracted = exists().where(
            KGDocumentExtraction.document_id == Document.id,
            KGDocumentExtraction.extractor_version == extractor_version,
            KGDocumentExtraction.status == "completed",
        )
        rows = await self._session.scalars(
            self._ready_in_workspace(user_id, workspace_id)
            .where(~extracted)
            .order_by(WorkspaceDocument.added_at, Document.id)
        )
        return list(rows)

    async def create_job(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        kind: str,
        extractor_version: str,
        call_budget: int,
    ) -> KGJob | None:
        """Insert a queued job; None if the workspace already has a queued or running one.

        The partial unique index makes a concurrent second insert wait and then do nothing.
        The caller has checked that the user owns the workspace.
        """
        job_id = await self._session.scalar(
            pg_insert(KGJob)
            .values(
                user_id=user_id,
                workspace_id=workspace_id,
                kind=kind,
                extractor_version=extractor_version,
                call_budget=call_budget,
            )
            .on_conflict_do_nothing(
                index_elements=["workspace_id"],
                index_where=KGJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .returning(KGJob.id)
        )
        if job_id is None:
            return None
        return await self._session.get(KGJob, job_id)

    async def get_job(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> KGJob | None:
        """The job, or None if it is missing or not the user's job in that workspace."""
        return await self._session.scalar(
            select(KGJob)
            .where(
                KGJob.id == job_id,
                KGJob.workspace_id == workspace_id,
                KGJob.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )

    async def active_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None:
        """The workspace's queued or running job, if any."""
        return await self._session.scalar(
            select(KGJob)
            .where(
                KGJob.workspace_id == workspace_id,
                KGJob.user_id == user_id,
                KGJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .execution_options(populate_existing=True)
        )

    async def latest_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None:
        """The workspace's most recent job, whatever its status."""
        return await self._session.scalar(
            select(KGJob)
            .where(KGJob.workspace_id == workspace_id, KGJob.user_id == user_id)
            .order_by(KGJob.created_at.desc(), KGJob.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )

    async def graph(self, user_id: UUID, workspace_id: UUID) -> KGGraph | None:
        """The workspace's current graph record, if one was built."""
        return await self._session.scalar(
            select(KGGraph).where(KGGraph.workspace_id == workspace_id, KGGraph.user_id == user_id)
        )

    async def start_job(self, user_id: UUID, job_id: UUID, *, documents_total: int) -> None:
        """Mark a queued job running in its extracting phase."""
        await self._session.execute(
            update(KGJob)
            .where(KGJob.id == job_id, KGJob.user_id == user_id)
            .values(
                status="running",
                phase="extracting",
                documents_total=documents_total,
                started_at=func.now(),
                heartbeat_at=func.now(),
            )
        )

    async def record_progress(
        self,
        user_id: UUID,
        job_id: UUID,
        *,
        documents_done: int,
        current_document_id: UUID | None,
        usage: JobUsage,
        phase: str | None = None,
    ) -> None:
        """Store the job's progress and usage so far."""
        values: dict[str, object] = {
            "documents_done": documents_done,
            "current_document_id": current_document_id,
            "llm_calls": usage.llm_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        if phase is not None:
            values["phase"] = phase
        await self._session.execute(
            update(KGJob).where(KGJob.id == job_id, KGJob.user_id == user_id).values(**values)
        )

    async def heartbeat(self, user_id: UUID, job_id: UUID) -> None:
        """Record that the job is still alive (only while it is queued or running)."""
        await self._session.execute(
            update(KGJob)
            .where(
                KGJob.id == job_id,
                KGJob.user_id == user_id,
                KGJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .values(heartbeat_at=func.now())
        )

    async def finish_job(
        self,
        user_id: UUID,
        job_id: UUID,
        *,
        status: str,
        usage: JobUsage,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark the job completed or failed with its final usage."""
        await self._session.execute(
            update(KGJob)
            .where(KGJob.id == job_id, KGJob.user_id == user_id)
            .values(
                status=status,
                current_document_id=None,
                llm_calls=usage.llm_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                error_code=error_code,
                error_message=error_message,
                finished_at=func.now(),
            )
        )

    async def fail_stale_jobs(
        self,
        *,
        older_than: timedelta,
        error_code: str,
        error_message: str,
        exclude: Collection[UUID] = (),
    ) -> int:
        """Fail queued or running jobs whose heartbeat is older than `older_than`.

        `exclude` holds jobs the caller is running. A system-wide sweep, so it is not scoped to
        one user. Returns the count.
        """
        conditions = [
            KGJob.status.in_(ACTIVE_JOB_STATUSES),
            KGJob.heartbeat_at < func.now() - older_than,
        ]
        if exclude:
            conditions.append(KGJob.id.not_in(list(exclude)))
        result = await self._session.execute(
            update(KGJob)
            .where(*conditions)
            .values(
                status="failed",
                current_document_id=None,
                error_code=error_code,
                error_message=error_message,
                finished_at=func.now(),
            )
            .returning(KGJob.id)
        )
        return len(result.all())

    async def document_chunks(self, user_id: UUID, document_id: UUID) -> list[ChunkRecord]:
        """Every chunk of the user's ready document in reading order; empty if it is gone."""
        rows = await self._session.execute(
            select(
                Chunk.id,
                Chunk.document_id,
                Document.title,
                Chunk.chunk_index,
                Chunk.page_start,
                Chunk.page_end,
                Chunk.section,
                Chunk.text,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.document_id == document_id,
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .order_by(Chunk.chunk_index)
        )
        return [
            ChunkRecord(
                chunk_id=row.id,
                document_id=row.document_id,
                document_title=row.title,
                chunk_index=row.chunk_index,
                page_start=row.page_start,
                page_end=row.page_end,
                section=row.section,
                text=row.text,
            )
            for row in rows
        ]

    async def save_extraction(
        self,
        user_id: UUID,
        document_id: UUID,
        extractor_version: str,
        extraction: PaperExtraction,
        *,
        llm_calls: int,
        tokens: int,
    ) -> bool:
        """Store one paper's extraction and its mentions; False if the document is gone.

        The document row is locked first, so a concurrent removal waits or wins. Storing the
        same version twice keeps the first completed one (idempotent); a failed attempt is
        replaced. Every mention must cite a chunk of this
        document and every relation must join two of its entity mentions (ValueError otherwise).
        """
        locked = await self._session.scalar(
            select(Document.id)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .with_for_update()
        )
        if locked is None:
            return False
        chunk_ids = set(
            await self._session.scalars(select(Chunk.id).where(Chunk.document_id == document_id))
        )
        _check_extraction(extraction, chunk_ids)
        extraction_id = await self._session.scalar(
            pg_insert(KGDocumentExtraction)
            .values(
                user_id=user_id,
                document_id=document_id,
                extractor_version=extractor_version,
                status=extraction.status,
                chunks_considered=extraction.chunks_considered,
                llm_calls=llm_calls,
                tokens=tokens,
                rejected_counts=extraction.rejected_counts,
            )
            .on_conflict_do_update(
                index_elements=["document_id", "extractor_version"],
                # Only a failed attempt (no mentions) is replaced; a completed one is kept.
                set_={
                    "status": extraction.status,
                    "chunks_considered": extraction.chunks_considered,
                    "llm_calls": llm_calls,
                    "tokens": tokens,
                    "rejected_counts": extraction.rejected_counts,
                    "created_at": func.now(),
                },
                where=KGDocumentExtraction.status == "failed",
            )
            .returning(KGDocumentExtraction.id)
        )
        if extraction_id is None:
            return True
        mention_ids: dict[str, UUID] = {}
        if extraction.entities:
            ids = await self._session.scalars(
                insert(KGEntityMention).returning(KGEntityMention.id, sort_by_parameter_order=True),
                [
                    {
                        "extraction_id": extraction_id,
                        "document_id": document_id,
                        "chunk_id": entity.chunk_id,
                        "entity_type": entity.entity_type,
                        "surface_text": entity.surface_text,
                        "normalized_key": entity.normalized_key,
                        "quote": entity.quote,
                    }
                    for entity in extraction.entities
                ],
            )
            mention_ids = dict(zip((e.key for e in extraction.entities), ids, strict=True))
        if extraction.relations:
            await self._session.execute(
                insert(KGRelationMention),
                [
                    {
                        "extraction_id": extraction_id,
                        "document_id": document_id,
                        "chunk_id": relation.chunk_id,
                        "source_mention_id": mention_ids[relation.source_key],
                        "target_mention_id": mention_ids[relation.target_key],
                        "relation_type": relation.relation_type,
                        "quote": relation.quote,
                        "entailment_score": relation.entailment_score,
                    }
                    for relation in extraction.relations
                ],
            )
        return True

    async def build_inputs(
        self, user_id: UUID, document_ids: Collection[UUID], extractor_version: str
    ) -> BuildInputs:
        """The mentions of the user's completed extractions of these papers, and the text of
        every passage they cite."""
        if not document_ids:
            return BuildInputs([], [], {})
        extraction_ids = (
            select(KGDocumentExtraction.id)
            .where(
                KGDocumentExtraction.user_id == user_id,
                KGDocumentExtraction.document_id.in_(list(document_ids)),
                KGDocumentExtraction.extractor_version == extractor_version,
                KGDocumentExtraction.status == "completed",
            )
            .scalar_subquery()
        )
        mentions = [
            MentionRow(
                id=row.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                entity_type=row.entity_type,
                surface_text=row.surface_text,
                normalized_key=row.normalized_key,
            )
            for row in await self._session.execute(
                select(
                    KGEntityMention.id,
                    KGEntityMention.document_id,
                    KGEntityMention.chunk_id,
                    KGEntityMention.entity_type,
                    KGEntityMention.surface_text,
                    KGEntityMention.normalized_key,
                )
                .where(KGEntityMention.extraction_id.in_(extraction_ids))
                .order_by(KGEntityMention.id)
            )
        ]
        relations = [
            RelationRow(
                id=row.id,
                document_id=row.document_id,
                source_mention_id=row.source_mention_id,
                target_mention_id=row.target_mention_id,
                relation_type=row.relation_type,
            )
            for row in await self._session.execute(
                select(
                    KGRelationMention.id,
                    KGRelationMention.document_id,
                    KGRelationMention.source_mention_id,
                    KGRelationMention.target_mention_id,
                    KGRelationMention.relation_type,
                )
                .where(KGRelationMention.extraction_id.in_(extraction_ids))
                .order_by(KGRelationMention.id)
            )
        ]
        chunk_ids = list({mention.chunk_id for mention in mentions})
        texts: dict[UUID, str] = {}
        if chunk_ids:
            rows = await self._session.execute(
                select(Chunk.id, Chunk.text).where(Chunk.id.in_(chunk_ids))
            )
            texts = {row.id: row.text for row in rows}
        return BuildInputs(mentions, relations, texts)

    async def replace_graph(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        job_id: UUID,
        source_fingerprint: str,
        nodes: Collection[NewNode],
        edges: Collection[NewEdge],
    ) -> None:
        """Replace the workspace's nodes and edges and record the build; commit is the caller's,
        so the old graph stays until the whole new one is written."""
        owned = await self._session.scalar(
            select(Workspace.id)
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .with_for_update()
        )
        if owned is None:
            return
        # Edges and both link tables cascade from the nodes.
        await self._session.execute(
            delete(KGNode).where(KGNode.workspace_id == workspace_id, KGNode.user_id == user_id)
        )
        if nodes:
            await self._session.execute(
                insert(KGNode),
                [
                    {
                        "id": node.id,
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                        "entity_type": node.entity_type,
                        "label": node.label,
                        "normalized_key": node.normalized_key,
                        "aliases": node.aliases,
                        "document_count": node.document_count,
                        "mention_count": len(node.mention_ids),
                    }
                    for node in nodes
                ],
            )
            await self._session.execute(
                insert(KGNodeMention),
                [{"node_id": n.id, "mention_id": m} for n in nodes for m in n.mention_ids],
            )
        if edges:
            await self._session.execute(
                insert(KGEdge),
                [
                    {
                        "id": edge.id,
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                        "relation_type": edge.relation_type,
                        "document_count": edge.document_count,
                        "mention_count": len(edge.relation_mention_ids),
                    }
                    for edge in edges
                ],
            )
            await self._session.execute(
                insert(KGEdgeMention),
                [
                    {"edge_id": e.id, "relation_mention_id": m}
                    for e in edges
                    for m in e.relation_mention_ids
                ],
            )
        values = {
            "user_id": user_id,
            "built_by_job_id": job_id,
            "built_at": func.now(),
            "source_fingerprint": source_fingerprint,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
        await self._session.execute(
            pg_insert(KGGraph)
            .values(workspace_id=workspace_id, **values)
            .on_conflict_do_update(index_elements=["workspace_id"], set_=values)
        )

    def _live_documents(self, user_id: UUID, workspace_id: UUID) -> Select[UUID]:
        """Ready papers currently linked to the user's workspace: the only valid evidence."""
        return self._ready_in_workspace(user_id, workspace_id)

    async def graph_view(
        self, user_id: UUID, workspace_id: UUID, *, max_nodes: int
    ) -> tuple[list[NodeView], list[EdgeView], bool]:
        """The most-supported nodes (at most `max_nodes`), the edges between them, and whether
        nodes were left out. Support counts only papers currently in the workspace; nodes and
        edges without such support are hidden."""
        live = self._live_documents(user_id, workspace_id)
        node_support = (
            select(
                KGNodeMention.node_id,
                func.count(distinct(KGEntityMention.document_id)).label("documents"),
                func.count().label("mentions"),
            )
            .join(KGEntityMention, KGEntityMention.id == KGNodeMention.mention_id)
            .where(KGEntityMention.document_id.in_(live))
            .group_by(KGNodeMention.node_id)
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    KGNode.id,
                    KGNode.entity_type,
                    KGNode.label,
                    KGNode.aliases,
                    node_support.c.documents,
                    node_support.c.mentions,
                )
                .join(node_support, node_support.c.node_id == KGNode.id)
                .where(KGNode.workspace_id == workspace_id, KGNode.user_id == user_id)
                .order_by(
                    node_support.c.documents.desc(),
                    node_support.c.mentions.desc(),
                    KGNode.label,
                    KGNode.id,
                )
                .limit(max_nodes + 1)
            )
        ).all()
        truncated = len(rows) > max_nodes
        nodes = [
            NodeView(
                id=row.id,
                entity_type=row.entity_type,
                label=row.label,
                aliases=list(row.aliases),
                document_count=row.documents,
                mention_count=row.mentions,
            )
            for row in rows[:max_nodes]
        ]
        shown = {node.id for node in nodes}
        edge_support = (
            select(
                KGEdgeMention.edge_id,
                func.count(distinct(KGRelationMention.document_id)).label("documents"),
                func.count().label("mentions"),
            )
            .join(KGRelationMention, KGRelationMention.id == KGEdgeMention.relation_mention_id)
            .where(KGRelationMention.document_id.in_(live))
            .group_by(KGEdgeMention.edge_id)
            .subquery()
        )
        edge_rows = await self._session.execute(
            select(
                KGEdge.id,
                KGEdge.source_node_id,
                KGEdge.target_node_id,
                KGEdge.relation_type,
                edge_support.c.documents,
                edge_support.c.mentions,
            )
            .join(edge_support, edge_support.c.edge_id == KGEdge.id)
            .where(KGEdge.workspace_id == workspace_id, KGEdge.user_id == user_id)
            .order_by(edge_support.c.documents.desc(), KGEdge.id)
        )
        edges = [
            EdgeView(
                id=row.id,
                source_node_id=row.source_node_id,
                target_node_id=row.target_node_id,
                relation_type=row.relation_type,
                document_count=row.documents,
                mention_count=row.mentions,
            )
            for row in edge_rows
            if row.source_node_id in shown and row.target_node_id in shown
        ]
        return nodes, edges, truncated

    async def node_evidence(
        self, user_id: UUID, workspace_id: UUID, node_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None:
        """A node's supporting passages from the workspace's current papers; None if the node is
        not in the user's workspace."""
        if not await self._owns(KGNode, user_id, workspace_id, node_id):
            return None
        statement = (
            select(
                KGEntityMention.id,
                KGEntityMention.document_id,
                KGEntityMention.chunk_id,
                KGEntityMention.quote,
            )
            .join(KGNodeMention, KGNodeMention.mention_id == KGEntityMention.id)
            .where(KGNodeMention.node_id == node_id)
        )
        return await self._evidence(
            statement, KGEntityMention, user_id, workspace_id, limit, offset
        )

    async def edge_evidence(
        self, user_id: UUID, workspace_id: UUID, edge_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None:
        """An edge's supporting passages from the workspace's current papers; None if the edge
        is not in the user's workspace."""
        if not await self._owns(KGEdge, user_id, workspace_id, edge_id):
            return None
        statement = (
            select(
                KGRelationMention.id,
                KGRelationMention.document_id,
                KGRelationMention.chunk_id,
                KGRelationMention.quote,
            )
            .join(KGEdgeMention, KGEdgeMention.relation_mention_id == KGRelationMention.id)
            .where(KGEdgeMention.edge_id == edge_id)
        )
        return await self._evidence(
            statement, KGRelationMention, user_id, workspace_id, limit, offset
        )

    async def _owns(
        self, model: type[KGNode] | type[KGEdge], user_id: UUID, workspace_id: UUID, row_id: UUID
    ) -> bool:
        found = await self._session.scalar(
            select(model.id).where(
                model.id == row_id, model.workspace_id == workspace_id, model.user_id == user_id
            )
        )
        return found is not None

    async def _evidence(
        self,
        statement: Select[UUID, UUID, UUID, str],
        mention: type[KGEntityMention] | type[KGRelationMention],
        user_id: UUID,
        workspace_id: UUID,
        limit: int,
        offset: int,
    ) -> list[EvidenceRow]:
        rows = await self._session.execute(
            statement.add_columns(Document.title, Chunk.page_start, Chunk.page_end, Chunk.section)
            .join(Chunk, Chunk.id == mention.chunk_id)
            .join(Document, Document.id == mention.document_id)
            .where(mention.document_id.in_(self._live_documents(user_id, workspace_id)))
            .order_by(Document.title, Chunk.page_start, mention.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            EvidenceRow(
                id=row.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                document_title=row.title,
                page_start=row.page_start,
                page_end=row.page_end,
                section=row.section,
                quote=row.quote,
            )
            for row in rows
        ]

    async def commit(self) -> None:
        """Commit the session's transaction."""
        await self._session.commit()


def _check_extraction(extraction: PaperExtraction, chunk_ids: set[UUID]) -> None:
    keys = [entity.key for entity in extraction.entities]
    if len(set(keys)) != len(keys):
        raise ValueError("Entity mention keys must be unique within an extraction.")
    cited = {e.chunk_id for e in extraction.entities} | {r.chunk_id for r in extraction.relations}
    if not cited <= chunk_ids:
        raise ValueError("A mention cites a chunk of another document.")
    known = set(keys)
    for relation in extraction.relations:
        if relation.source_key not in known or relation.target_key not in known:
            raise ValueError("A relation refers to an unknown entity mention.")
        if relation.source_key == relation.target_key:
            raise ValueError("A relation must join two different entity mentions.")


def knowledge_graph_store_factory(
    sessions: async_sessionmaker[AsyncSession],
) -> Callable[[], AbstractAsyncContextManager[KnowledgeGraphRepository]]:
    """Open a repository on a fresh session for each unit of background work."""

    @asynccontextmanager
    async def open_store() -> AsyncIterator[KnowledgeGraphRepository]:
        async with sessions() as session:
            yield KnowledgeGraphRepository(session)

    return open_store
