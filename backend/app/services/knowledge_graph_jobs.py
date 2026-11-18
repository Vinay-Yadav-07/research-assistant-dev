"""S10 Knowledge Graph Service: background jobs (FR-33, SRS §9.1, D-081).

`start` records a queued job (one active job per workspace, enforced by the database) and runs
it in a task of its own. Jobs run one at a time across the application, so only one calls the
graph-tier LLM. Phase A reads every ready paper of the workspace without a current extraction
and commits each paper's extraction on its own, so a failed or interrupted job keeps the papers
it finished; a paper interrupted midway is read again next time. Phase B rebuilds the workspace
graph in one transaction (the builder), so a failed build keeps the previous graph.

While a job is queued or running it writes a heartbeat every `heartbeat_seconds`, independent of
its progress, so waiting for rate limits never looks like a dead job. Jobs never resume by
themselves: the sweep fails queued or running jobs this process is not running whose heartbeat
is stale, and the next Generate or Update continues from the completed papers.
"""

import asyncio
import hashlib
import logging
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import (
    AppError,
    CallBudgetExceededError,
    ConflictError,
    DependencyUnavailableError,
    NoReadyDocumentsError,
    NotFoundError,
)
from app.models.knowledge_graph import KGGraph, KGJob
from app.providers.usage import RunUsage, track_usage
from app.repositories.chunks import ChunkRecord
from app.repositories.knowledge_graph import (
    EdgeView,
    EvidenceRow,
    JobUsage,
    NodeView,
    PaperExtraction,
)
from app.schemas.conversations import CitationRead
from app.schemas.knowledge_graph import (
    GraphState,
    KGEdgeRead,
    KGJobRead,
    KGNodeRead,
    KnowledgeGraphRead,
)

logger = logging.getLogger(__name__)

INTERRUPTED = "interrupted"
INTERRUPTED_MESSAGE = "Graph generation was interrupted, for example by a server restart."
INTERNAL_ERROR = "internal_error"
INTERNAL_ERROR_MESSAGE = "Graph generation failed unexpectedly."
NOT_AVAILABLE = "Knowledge graph generation is not available yet."


class KnowledgeGraphStore(Protocol):
    """Persistence the jobs need; `KnowledgeGraphRepository` implements it."""

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool: ...

    async def ready_document_ids(self, user_id: UUID, workspace_id: UUID) -> list[UUID]: ...

    async def pending_document_ids(
        self, user_id: UUID, workspace_id: UUID, extractor_version: str
    ) -> list[UUID]: ...

    async def create_job(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        kind: str,
        extractor_version: str,
        call_budget: int,
    ) -> KGJob | None: ...

    async def get_job(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> KGJob | None: ...

    async def active_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None: ...

    async def latest_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None: ...

    async def graph(self, user_id: UUID, workspace_id: UUID) -> KGGraph | None: ...

    async def start_job(self, user_id: UUID, job_id: UUID, *, documents_total: int) -> None: ...

    async def record_progress(
        self,
        user_id: UUID,
        job_id: UUID,
        *,
        documents_done: int,
        current_document_id: UUID | None,
        usage: JobUsage,
        phase: str | None = None,
    ) -> None: ...

    async def heartbeat(self, user_id: UUID, job_id: UUID) -> None: ...

    async def finish_job(
        self,
        user_id: UUID,
        job_id: UUID,
        *,
        status: str,
        usage: JobUsage,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def fail_stale_jobs(
        self,
        *,
        older_than: timedelta,
        error_code: str,
        error_message: str,
        exclude: Collection[UUID] = (),
    ) -> int: ...

    async def document_chunks(self, user_id: UUID, document_id: UUID) -> list[ChunkRecord]: ...

    async def save_extraction(
        self,
        user_id: UUID,
        document_id: UUID,
        extractor_version: str,
        extraction: PaperExtraction,
        *,
        llm_calls: int,
        tokens: int,
    ) -> bool: ...

    async def graph_view(
        self, user_id: UUID, workspace_id: UUID, *, max_nodes: int
    ) -> tuple[list[NodeView], list[EdgeView], bool]: ...

    async def node_evidence(
        self, user_id: UUID, workspace_id: UUID, node_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None: ...

    async def edge_evidence(
        self, user_id: UUID, workspace_id: UUID, edge_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None: ...

    async def commit(self) -> None: ...


# Opens a store on a fresh session; the session closes (rolling back anything uncommitted)
# when the context exits.
StoreFactory = Callable[[], AbstractAsyncContextManager[KnowledgeGraphStore]]


class CallBudget:
    """The LLM calls a job may still make; the extractor takes one before every call."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self.used = 0

    def take(self) -> None:
        """Count one call, or raise `CallBudgetExceededError` when none are left."""
        if self.used >= self._limit:
            raise CallBudgetExceededError(
                f"This run reached its limit of {self._limit} model calls.",
                details={"call_budget": self._limit},
            )
        self.used += 1

    def ensure(self, calls: int) -> None:
        """Raise `CallBudgetExceededError` now if `calls` more calls would not fit, so a paper is
        never stopped halfway for lack of budget."""
        if self.used + calls > self._limit:
            raise CallBudgetExceededError(
                f"This run reached its limit of {self._limit} model calls.",
                details={"call_budget": self._limit, "needed": calls},
            )


class PaperExtractor(Protocol):
    """Reads one paper's chunks into validated entity and relation mentions (Phase A)."""

    @property
    def version(self) -> str:
        """Prompt and schema version; a new version makes every paper pending again."""
        ...

    async def extract(
        self, document_id: UUID, chunks: Sequence[ChunkRecord], budget: CallBudget
    ) -> PaperExtraction: ...


class GraphBuilder(Protocol):
    """Rebuilds a workspace's nodes and edges from its papers' extractions in one transaction
    (Phase B), recording `source_fingerprint` of the papers it used."""

    async def build(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> None: ...


@dataclass(frozen=True)
class KGJobOptions:
    """Heartbeat, stale time, and per-job LLM call budget (SRS §9.1)."""

    heartbeat_seconds: float
    stale_after: timedelta
    call_budget: int
    max_nodes: int = 500

    @classmethod
    def from_settings(cls, settings: Settings) -> "KGJobOptions":
        """Read the options from the application settings."""
        return cls(
            heartbeat_seconds=settings.kg_heartbeat_seconds,
            stale_after=timedelta(minutes=settings.kg_job_stale_minutes),
            call_budget=settings.kg_max_calls_per_job,
            max_nodes=settings.kg_graph_max_nodes,
        )


def source_fingerprint(document_ids: Collection[UUID], extractor_version: str) -> str:
    """Identifies the papers and extractor a graph was built from (order does not matter)."""
    parts = [extractor_version, *sorted(str(document_id) for document_id in document_ids)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def graph_state(
    graph: KGGraph | None, active: KGJob | None, last: KGJob | None, *, stale: bool
) -> GraphState:
    """What the graph page shows: an active job first, then a failed last job, then the graph."""
    if active is not None:
        if graph is not None:
            return "updating"
        return "queued" if active.status == "queued" else "generating"
    if last is not None and last.status == "failed":
        return "failed"
    if graph is None:
        return "empty"
    return "update_available" if stale else "ready"


def _citation(row: EvidenceRow) -> CitationRead:
    return CitationRead(
        id=row.id,
        source_type="workspace",
        document_id=row.document_id,
        chunk_id=row.chunk_id,
        document_title=row.document_title,
        page_start=row.page_start,
        page_end=row.page_end,
        section=row.section,
        quote=row.quote,
    )


def _usage(usage: RunUsage) -> JobUsage:
    return JobUsage(
        llm_calls=usage.calls, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
    )


class KnowledgeGraphRunner:
    """Starts knowledge graph jobs and reports graph state; one per application.

    Without an extractor and a builder, the state can be read but no job can start.
    """

    def __init__(
        self,
        stores: StoreFactory,
        *,
        extractor: PaperExtractor | None,
        builder: GraphBuilder | None,
        options: KGJobOptions,
    ) -> None:
        self._stores = stores
        self._extractor = extractor
        self._builder = builder
        self._options = options
        # One job calls the LLM at a time; later jobs wait here in status "queued".
        self._slots = asyncio.Semaphore(1)
        # Queued or running here; the sweep must not fail these.
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def start(self, user_id: UUID, workspace_id: UUID) -> tuple[KGJobRead, bool]:
        """Start Generate (no graph yet) or Update; returns the job and whether it is new.

        If the workspace already has an active job, that job is returned instead. Raises
        `NotFoundError` for a missing or non-owned workspace, `NoReadyDocumentsError` when it
        has no ready papers, and `DependencyUnavailableError` when extraction is not configured.
        """
        async with self._stores() as store:
            if not await store.workspace_owned(user_id, workspace_id):
                raise NotFoundError("Workspace not found.")
            if self._extractor is None or self._builder is None:
                raise DependencyUnavailableError(NOT_AVAILABLE)
            if not await store.ready_document_ids(user_id, workspace_id):
                raise NoReadyDocumentsError()
            kind = "update" if await store.graph(user_id, workspace_id) else "generate"
            # Twice: the active job may finish between a refused insert and the read.
            for _ in range(2):
                job = await store.create_job(
                    user_id,
                    workspace_id,
                    kind=kind,
                    extractor_version=self._extractor.version,
                    call_budget=self._options.call_budget,
                )
                if job is not None:
                    await store.commit()
                    break
                active = await store.active_job(user_id, workspace_id)
                if active is not None:
                    return KGJobRead.model_validate(active), False
            else:
                raise ConflictError("Another graph job just changed state; try again.")
        self._tasks[job.id] = asyncio.create_task(self._execute(user_id, workspace_id, job.id))
        return KGJobRead.model_validate(job), True

    async def get_job(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> KGJobRead:
        """One of the user's jobs in that workspace; `NotFoundError` otherwise."""
        async with self._stores() as store:
            job = await store.get_job(user_id, workspace_id, job_id)
        if job is None:
            raise NotFoundError("Job not found.")
        return KGJobRead.model_validate(job)

    async def graph_status(self, user_id: UUID, workspace_id: UUID) -> KnowledgeGraphRead:
        """The workspace graph's state; `NotFoundError` for a missing or non-owned workspace."""
        async with self._stores() as store:
            if not await store.workspace_owned(user_id, workspace_id):
                raise NotFoundError("Workspace not found.")
            ready = await store.ready_document_ids(user_id, workspace_id)
            graph = await store.graph(user_id, workspace_id)
            active = await store.active_job(user_id, workspace_id)
            last = await store.latest_job(user_id, workspace_id)
            nodes, edges, truncated = await store.graph_view(
                user_id, workspace_id, max_nodes=self._options.max_nodes
            )
        stale = (
            graph is not None
            and self._extractor is not None
            and graph.source_fingerprint != source_fingerprint(ready, self._extractor.version)
        )
        return KnowledgeGraphRead(
            state=graph_state(graph, active, last, stale=stale),
            stale=stale,
            ready_documents=len(ready),
            built_at=graph.built_at if graph else None,
            node_count=graph.node_count if graph else 0,
            edge_count=graph.edge_count if graph else 0,
            active_job=KGJobRead.model_validate(active) if active else None,
            last_job=KGJobRead.model_validate(last) if last else None,
            nodes=[KGNodeRead.model_validate(node) for node in nodes],
            edges=[KGEdgeRead.model_validate(edge) for edge in edges],
            truncated=truncated,
        )

    async def node_evidence(
        self, user_id: UUID, workspace_id: UUID, node_id: UUID, *, limit: int, offset: int
    ) -> list[CitationRead]:
        """A node's supporting passages, shaped for the source viewer; `NotFoundError` if the
        node is not in the user's workspace."""
        async with self._stores() as store:
            rows = await store.node_evidence(
                user_id, workspace_id, node_id, limit=limit, offset=offset
            )
        if rows is None:
            raise NotFoundError("Node not found.")
        return [_citation(row) for row in rows]

    async def edge_evidence(
        self, user_id: UUID, workspace_id: UUID, edge_id: UUID, *, limit: int, offset: int
    ) -> list[CitationRead]:
        """An edge's supporting passages (each quote states the relationship)."""
        async with self._stores() as store:
            rows = await store.edge_evidence(
                user_id, workspace_id, edge_id, limit=limit, offset=offset
            )
        if rows is None:
            raise NotFoundError("Edge not found.")
        return [_citation(row) for row in rows]

    async def fail_stale(self) -> int:
        """Fail queued or running jobs nobody is running any more (SRS §9.1)."""
        async with self._stores() as store:
            count = await store.fail_stale_jobs(
                older_than=self._options.stale_after,
                error_code=INTERRUPTED,
                error_message=INTERRUPTED_MESSAGE,
                exclude=set(self._tasks),
            )
            await store.commit()
        if count:
            logger.warning("Marked %d interrupted knowledge graph job(s) as failed", count)
        return count

    async def sweep_periodically(self, interval_seconds: float) -> None:
        """Run `fail_stale` every `interval_seconds` until cancelled; errors are logged."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.fail_stale()
            except Exception:
                logger.exception("Periodic sweep of stale knowledge graph jobs failed")

    async def aclose(self) -> None:
        """Cancel jobs still running; after a restart the sweep fails them as interrupted."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> None:
        beat = asyncio.create_task(self._beat(user_id, job_id))
        try:
            async with self._slots:
                with track_usage() as usage:
                    try:
                        await self._run(user_id, workspace_id, job_id, usage)
                    except Exception as error:
                        await self._fail(user_id, job_id, error, usage)
        finally:
            beat.cancel()
            with suppress(asyncio.CancelledError):
                await beat
            self._tasks.pop(job_id, None)

    async def _run(self, user_id: UUID, workspace_id: UUID, job_id: UUID, usage: RunUsage) -> None:
        assert self._extractor is not None and self._builder is not None
        version = self._extractor.version
        async with self._stores() as store:
            pending = await store.pending_document_ids(user_id, workspace_id, version)
            await store.start_job(user_id, job_id, documents_total=len(pending))
            await store.commit()
        budget = CallBudget(self._options.call_budget)
        for done, document_id in enumerate(pending):
            await self._progress(user_id, job_id, done, document_id, usage)
            await self._extract(user_id, document_id, budget)
        await self._progress(user_id, job_id, len(pending), None, usage, phase="building")
        await self._builder.build(user_id, workspace_id, job_id)
        async with self._stores() as store:
            await store.finish_job(user_id, job_id, status="completed", usage=_usage(usage))
            await store.commit()
        logger.info(
            "Knowledge graph job %s completed: %d papers read, %d LLM calls",
            job_id,
            len(pending),
            usage.calls,
        )

    async def _extract(self, user_id: UUID, document_id: UUID, budget: CallBudget) -> None:
        """Read one paper and commit its extraction; a paper removed meanwhile is skipped."""
        assert self._extractor is not None
        async with self._stores() as store:
            chunks = await store.document_chunks(user_id, document_id)
        if not chunks:
            logger.info("Document %s left before the knowledge graph read it", document_id)
            return
        # The LLM calls run without a session; the write opens a new one.
        with track_usage() as paper:
            extraction = await self._extractor.extract(document_id, chunks, budget)
        async with self._stores() as store:
            saved = await store.save_extraction(
                user_id,
                document_id,
                self._extractor.version,
                extraction,
                llm_calls=paper.calls,
                tokens=paper.total_tokens,
            )
            await store.commit()
        if not saved:
            logger.info("Document %s left while the knowledge graph read it", document_id)

    async def _progress(
        self,
        user_id: UUID,
        job_id: UUID,
        done: int,
        document_id: UUID | None,
        usage: RunUsage,
        *,
        phase: str | None = None,
    ) -> None:
        async with self._stores() as store:
            await store.record_progress(
                user_id,
                job_id,
                documents_done=done,
                current_document_id=document_id,
                usage=_usage(usage),
                phase=phase,
            )
            await store.commit()

    async def _beat(self, user_id: UUID, job_id: UUID) -> None:
        """Write a heartbeat every `heartbeat_seconds` until cancelled; errors are logged."""
        while True:
            await asyncio.sleep(self._options.heartbeat_seconds)
            try:
                async with self._stores() as store:
                    await store.heartbeat(user_id, job_id)
                    await store.commit()
            except Exception:
                logger.exception("Heartbeat of knowledge graph job %s failed", job_id)

    async def _fail(self, user_id: UUID, job_id: UUID, error: Exception, usage: RunUsage) -> None:
        """Mark the job failed in a transaction of its own; completed papers stay stored."""
        if isinstance(error, AppError):
            code, message = error.code, error.message
            logger.warning("Knowledge graph job %s failed: %s", job_id, code)
        else:
            code, message = INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE
            logger.exception("Knowledge graph job %s failed", job_id)
        try:
            async with self._stores() as store:
                await store.finish_job(
                    user_id,
                    job_id,
                    status="failed",
                    usage=_usage(usage),
                    error_code=code,
                    error_message=message,
                )
                await store.commit()
        except Exception:
            # The sweep fails it later once its heartbeat stops.
            logger.exception("Could not mark knowledge graph job %s as failed", job_id)
