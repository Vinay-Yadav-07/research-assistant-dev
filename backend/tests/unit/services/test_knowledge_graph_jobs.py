"""Knowledge graph jobs with an in-memory store and scripted extractor (SRS §9.1, D-081)."""

import asyncio
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import (
    CallBudgetExceededError,
    ConflictError,
    DependencyUnavailableError,
    LLMQuotaExceededError,
    NoReadyDocumentsError,
    NotFoundError,
)
from app.models.knowledge_graph import KGGraph, KGJob
from app.providers.llm import TokenUsage
from app.providers.usage import record_call
from app.repositories.chunks import ChunkRecord
from app.repositories.knowledge_graph import (
    EdgeView,
    EvidenceRow,
    JobUsage,
    NewEntityMention,
    NodeView,
    PaperExtraction,
)
from app.services.knowledge_graph_jobs import (
    INTERNAL_ERROR,
    INTERRUPTED,
    CallBudget,
    KGJobOptions,
    KnowledgeGraphRunner,
    graph_state,
    source_fingerprint,
)

USER = uuid4()
WORKSPACE = uuid4()
VERSION = "kg-test.v1"
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def chunk(document_id: UUID, index: int = 0) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=uuid4(),
        document_id=document_id,
        document_title="Paper",
        chunk_index=index,
        page_start=1,
        page_end=1,
        section="Results",
        text="LSTM was evaluated on the M4 dataset.",
    )


@dataclass
class InMemoryKGStore:
    """Shared state for every `open()`; writes apply at once (the runner commits each step)."""

    workspaces: dict[UUID, UUID] = field(default_factory=lambda: {WORKSPACE: USER})
    ready: dict[UUID, list[UUID]] = field(default_factory=dict)
    chunks: dict[UUID, list[ChunkRecord]] = field(default_factory=dict)
    extracted: dict[UUID, PaperExtraction] = field(default_factory=dict)
    jobs: dict[UUID, KGJob] = field(default_factory=dict)
    graphs: dict[UUID, KGGraph] = field(default_factory=dict)
    heartbeats: list[UUID] = field(default_factory=list)
    stale_excluded: list[set[UUID]] = field(default_factory=list)
    refuse_create: bool = False
    gone: set[UUID] = field(default_factory=set)
    nodes: dict[UUID, list[NodeView]] = field(default_factory=dict)
    evidence: dict[UUID, list[EvidenceRow]] = field(default_factory=dict)

    def add_paper(self, workspace_id: UUID = WORKSPACE) -> UUID:
        document_id = uuid4()
        self.ready.setdefault(workspace_id, []).append(document_id)
        self.chunks[document_id] = [chunk(document_id, 0), chunk(document_id, 1)]
        return document_id

    @asynccontextmanager
    async def open(self) -> AsyncIterator["InMemoryKGStore"]:
        yield self

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        return self.workspaces.get(workspace_id) == user_id

    async def ready_document_ids(self, user_id: UUID, workspace_id: UUID) -> list[UUID]:
        if self.workspaces.get(workspace_id) != user_id:
            return []
        return sorted(self.ready.get(workspace_id, []))

    async def pending_document_ids(
        self, user_id: UUID, workspace_id: UUID, extractor_version: str
    ) -> list[UUID]:
        return [d for d in self.ready.get(workspace_id, []) if d not in self.extracted]

    async def create_job(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        kind: str,
        extractor_version: str,
        call_budget: int,
    ) -> KGJob | None:
        if self.refuse_create or any(
            j.workspace_id == workspace_id and j.status in ("queued", "running")
            for j in self.jobs.values()
        ):
            return None
        job = KGJob(
            id=uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            kind=kind,
            status="queued",
            phase=None,
            documents_total=0,
            documents_done=0,
            current_document_id=None,
            llm_calls=0,
            input_tokens=0,
            output_tokens=0,
            call_budget=call_budget,
            error_code=None,
            error_message=None,
            extractor_version=extractor_version,
            created_at=NOW + timedelta(seconds=len(self.jobs)),
            started_at=None,
            heartbeat_at=NOW,
            finished_at=None,
        )
        self.jobs[job.id] = job
        return job

    async def get_job(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> KGJob | None:
        job = self.jobs.get(job_id)
        if job is None or (job.user_id, job.workspace_id) != (user_id, workspace_id):
            return None
        return job

    async def active_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None:
        return next(
            (
                j
                for j in self.jobs.values()
                if (j.user_id, j.workspace_id) == (user_id, workspace_id)
                and j.status in ("queued", "running")
            ),
            None,
        )

    async def latest_job(self, user_id: UUID, workspace_id: UUID) -> KGJob | None:
        own = [
            j for j in self.jobs.values() if (j.user_id, j.workspace_id) == (user_id, workspace_id)
        ]
        return max(own, key=lambda j: j.created_at, default=None)

    async def graph(self, user_id: UUID, workspace_id: UUID) -> KGGraph | None:
        graph = self.graphs.get(workspace_id)
        return graph if graph is not None and graph.user_id == user_id else None

    async def start_job(self, user_id: UUID, job_id: UUID, *, documents_total: int) -> None:
        job = self.jobs[job_id]
        job.status, job.phase, job.documents_total = "running", "extracting", documents_total

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
        job = self.jobs[job_id]
        job.documents_done, job.current_document_id = documents_done, current_document_id
        job.llm_calls = usage.llm_calls
        if phase is not None:
            job.phase = phase

    async def heartbeat(self, user_id: UUID, job_id: UUID) -> None:
        self.heartbeats.append(job_id)

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
        job = self.jobs[job_id]
        job.status, job.error_code, job.error_message = status, error_code, error_message
        job.llm_calls, job.input_tokens, job.output_tokens = (
            usage.llm_calls,
            usage.input_tokens,
            usage.output_tokens,
        )
        job.current_document_id = None

    async def fail_stale_jobs(
        self,
        *,
        older_than: timedelta,
        error_code: str,
        error_message: str,
        exclude: Collection[UUID] = (),
    ) -> int:
        self.stale_excluded.append(set(exclude))
        stale = [
            j
            for j in self.jobs.values()
            if j.status in ("queued", "running") and j.id not in exclude
        ]
        for job in stale:
            job.status, job.error_code = "failed", error_code
        return len(stale)

    async def document_chunks(self, user_id: UUID, document_id: UUID) -> list[ChunkRecord]:
        return [] if document_id in self.gone else self.chunks.get(document_id, [])

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
        self.extracted.setdefault(document_id, extraction)
        return True

    async def graph_view(
        self, user_id: UUID, workspace_id: UUID, *, max_nodes: int
    ) -> tuple[list[NodeView], list[EdgeView], bool]:
        return list(self.nodes.get(workspace_id, []))[:max_nodes], [], False

    async def node_evidence(
        self, user_id: UUID, workspace_id: UUID, node_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None:
        if self.workspaces.get(workspace_id) != user_id:
            return None
        return self.evidence.get(node_id)

    async def edge_evidence(
        self, user_id: UUID, workspace_id: UUID, edge_id: UUID, *, limit: int, offset: int
    ) -> list[EvidenceRow] | None:
        return None

    async def commit(self) -> None:
        pass


class ScriptedExtractor:
    """Makes `calls_per_paper` fake LLM calls per paper; `fail_on` papers raise an error."""

    version = VERSION

    def __init__(
        self,
        calls_per_paper: int = 2,
        fail_on: dict[UUID, Exception] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.calls_per_paper = calls_per_paper
        self.fail_on = fail_on or {}
        self.gate = gate
        self.read: list[UUID] = []

    async def extract(
        self, document_id: UUID, chunks: Sequence[ChunkRecord], budget: CallBudget
    ) -> PaperExtraction:
        self.read.append(document_id)
        if self.gate is not None:
            await self.gate.wait()
        for _ in range(self.calls_per_paper):
            budget.take()
            record_call("fake-graph", TokenUsage(input_tokens=100, output_tokens=20))
        if document_id in self.fail_on:
            raise self.fail_on[document_id]
        return PaperExtraction(
            chunks_considered=len(chunks),
            entities=[
                NewEntityMention(
                    key="m1",
                    chunk_id=chunks[0].chunk_id,
                    entity_type="method",
                    surface_text="LSTM",
                    normalized_key="lstm",
                    quote=chunks[0].text,
                )
            ],
        )


class RecordingBuilder:
    def __init__(self, store: InMemoryKGStore, error: Exception | None = None) -> None:
        self.store = store
        self.error = error
        self.built: list[tuple[UUID, UUID]] = []

    async def build(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> None:
        if self.error is not None:
            raise self.error
        self.built.append((workspace_id, job_id))
        ready = await self.store.ready_document_ids(user_id, workspace_id)
        self.store.graphs[workspace_id] = KGGraph(
            workspace_id=workspace_id,
            user_id=user_id,
            built_by_job_id=job_id,
            built_at=NOW,
            source_fingerprint=source_fingerprint(ready, VERSION),
            node_count=1,
            edge_count=0,
        )


OPTIONS = KGJobOptions(heartbeat_seconds=60, stale_after=timedelta(minutes=10), call_budget=50)


def runner(
    store: InMemoryKGStore,
    extractor: ScriptedExtractor | None = None,
    builder: RecordingBuilder | None = None,
    options: KGJobOptions = OPTIONS,
) -> KnowledgeGraphRunner:
    return KnowledgeGraphRunner(
        store.open,
        extractor=extractor if extractor is not None else ScriptedExtractor(),
        builder=builder if builder is not None else RecordingBuilder(store),
        options=options,
    )


async def finished(r: KnowledgeGraphRunner) -> None:
    """Wait until every job task of the runner is done."""
    await asyncio.gather(*list(r._tasks.values()), return_exceptions=True)


async def test_generate_reads_every_paper_then_builds_and_completes() -> None:
    store = InMemoryKGStore()
    papers = [store.add_paper(), store.add_paper()]
    extractor = ScriptedExtractor()
    builder = RecordingBuilder(store)
    r = runner(store, extractor, builder)

    job, created = await r.start(USER, WORKSPACE)
    await finished(r)

    assert created and job.kind == "generate" and job.status == "queued"
    assert extractor.read == papers
    assert set(store.extracted) == set(papers)
    assert builder.built == [(WORKSPACE, job.id)]
    done = store.jobs[job.id]
    assert (done.status, done.phase, done.documents_total, done.documents_done) == (
        "completed",
        "building",
        2,
        2,
    )
    assert (done.llm_calls, done.input_tokens, done.output_tokens) == (4, 400, 80)
    assert done.error_code is None
    assert r._tasks == {}


async def test_update_reads_only_papers_without_an_extraction() -> None:
    store = InMemoryKGStore()
    first = store.add_paper()
    r = runner(store)
    await r.start(USER, WORKSPACE)
    await finished(r)
    second = store.add_paper()
    extractor = ScriptedExtractor()
    r = runner(store, extractor)

    job, created = await r.start(USER, WORKSPACE)
    await finished(r)

    assert created and job.kind == "update"
    assert extractor.read == [second]
    assert first in store.extracted
    assert store.jobs[job.id].status == "completed"


async def test_a_second_start_returns_the_active_job() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    gate = asyncio.Event()
    r = runner(store, ScriptedExtractor(gate=gate))

    first, created_first = await r.start(USER, WORKSPACE)
    again, created_again = await r.start(USER, WORKSPACE)
    gate.set()
    await finished(r)

    assert created_first and not created_again
    assert again.id == first.id
    assert len(store.jobs) == 1


async def test_start_rejects_other_users_empty_workspaces_and_missing_extraction() -> None:
    store = InMemoryKGStore()
    with pytest.raises(NotFoundError):
        await runner(store).start(uuid4(), WORKSPACE)
    with pytest.raises(NoReadyDocumentsError):
        await runner(store).start(USER, WORKSPACE)
    store.add_paper()
    unconfigured = KnowledgeGraphRunner(store.open, extractor=None, builder=None, options=OPTIONS)
    with pytest.raises(DependencyUnavailableError):
        await unconfigured.start(USER, WORKSPACE)
    # The owner check comes first, so a stranger learns nothing about configuration.
    with pytest.raises(NotFoundError):
        await unconfigured.start(uuid4(), WORKSPACE)
    assert store.jobs == {}


async def test_quota_failure_keeps_the_papers_already_read_and_skips_the_build() -> None:
    store = InMemoryKGStore()
    first = store.add_paper()
    second = store.add_paper()
    builder = RecordingBuilder(store)
    extractor = ScriptedExtractor(fail_on={second: LLMQuotaExceededError()})
    r = runner(store, extractor, builder)

    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    failed = store.jobs[job.id]
    assert (failed.status, failed.error_code) == ("failed", "llm_quota_exhausted")
    assert failed.documents_done == 1
    assert failed.llm_calls == 4
    assert set(store.extracted) == {first}
    assert builder.built == []


async def test_retry_after_a_failure_continues_from_the_completed_papers() -> None:
    store = InMemoryKGStore()
    first = store.add_paper()
    second = store.add_paper()
    r = runner(store, ScriptedExtractor(fail_on={second: LLMQuotaExceededError()}))
    await r.start(USER, WORKSPACE)
    await finished(r)
    extractor = ScriptedExtractor()
    r = runner(store, extractor)

    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    assert extractor.read == [second]
    assert set(store.extracted) == {first, second}
    assert store.jobs[job.id].status == "completed"


async def test_the_call_budget_stops_the_job() -> None:
    store = InMemoryKGStore()
    first = store.add_paper()
    store.add_paper()
    options = KGJobOptions(heartbeat_seconds=60, stale_after=timedelta(minutes=10), call_budget=3)
    r = runner(store, ScriptedExtractor(calls_per_paper=2), options=options)

    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    failed = store.jobs[job.id]
    assert failed.status == "failed"
    assert failed.error_code == "budget_exceeded"
    assert "3 model calls" in (failed.error_message or "")
    assert set(store.extracted) == {first}


async def test_an_unexpected_error_fails_the_job_with_a_generic_message() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    r = runner(store, builder=RecordingBuilder(store, error=RuntimeError("boom")))

    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    failed = store.jobs[job.id]
    assert (failed.status, failed.error_code) == ("failed", INTERNAL_ERROR)
    assert "boom" not in (failed.error_message or "")
    assert store.graphs == {}


async def test_a_paper_removed_before_it_is_read_is_skipped() -> None:
    store = InMemoryKGStore()
    removed = store.add_paper()
    kept = store.add_paper()
    store.gone.add(removed)
    extractor = ScriptedExtractor()
    r = runner(store, extractor)

    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    assert extractor.read == [kept]
    assert store.jobs[job.id].status == "completed"


async def test_heartbeats_continue_while_the_job_waits() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    gate = asyncio.Event()
    options = KGJobOptions(heartbeat_seconds=0.01, stale_after=timedelta(minutes=10), call_budget=9)
    r = runner(store, ScriptedExtractor(gate=gate), options=options)

    job, _ = await r.start(USER, WORKSPACE)
    await asyncio.sleep(0.05)
    beats_while_waiting = store.heartbeats.count(job.id)
    gate.set()
    await finished(r)
    await asyncio.sleep(0.03)

    assert beats_while_waiting >= 2
    assert store.heartbeats.count(job.id) <= beats_while_waiting + 1


async def test_the_sweep_never_fails_a_job_this_process_is_running() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    gate = asyncio.Event()
    r = runner(store, ScriptedExtractor(gate=gate))
    job, _ = await r.start(USER, WORKSPACE)
    await asyncio.sleep(0)

    assert await r.fail_stale() == 0
    assert store.stale_excluded[-1] == {job.id}
    gate.set()
    await finished(r)
    assert store.jobs[job.id].status == "completed"


async def test_the_sweep_fails_orphaned_jobs_as_interrupted() -> None:
    store = InMemoryKGStore()
    orphan = await store.create_job(
        USER, WORKSPACE, kind="generate", extractor_version=VERSION, call_budget=5
    )
    assert orphan is not None

    assert await runner(store).fail_stale() == 1
    assert (orphan.status, orphan.error_code) == ("failed", INTERRUPTED)


async def test_jobs_of_different_workspaces_run_one_at_a_time() -> None:
    other = uuid4()
    store = InMemoryKGStore(workspaces={WORKSPACE: USER, other: USER})
    first_paper = store.add_paper(WORKSPACE)
    store.add_paper(other)
    gate = asyncio.Event()
    extractor = ScriptedExtractor(gate=gate)
    r = runner(store, extractor)

    first, _ = await r.start(USER, WORKSPACE)
    second, _ = await r.start(USER, other)
    await asyncio.sleep(0.01)

    assert extractor.read == [first_paper]
    assert store.jobs[second.id].status == "queued"
    gate.set()
    await finished(r)
    assert {store.jobs[first.id].status, store.jobs[second.id].status} == {"completed"}


async def test_a_refused_insert_without_an_active_job_is_a_conflict() -> None:
    store = InMemoryKGStore(refuse_create=True)
    store.add_paper()

    with pytest.raises(ConflictError):
        await runner(store).start(USER, WORKSPACE)


async def test_graph_status_reports_state_staleness_and_jobs() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    r = runner(store)

    empty = await r.graph_status(USER, WORKSPACE)
    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)
    ready = await r.graph_status(USER, WORKSPACE)
    store.add_paper()
    changed = await r.graph_status(USER, WORKSPACE)

    assert (empty.state, empty.ready_documents, empty.last_job) == ("empty", 1, None)
    assert (ready.state, ready.stale, ready.node_count) == ("ready", False, 1)
    assert ready.last_job is not None and ready.last_job.id == job.id
    assert (changed.state, changed.stale, changed.ready_documents) == ("update_available", True, 2)
    with pytest.raises(NotFoundError):
        await r.graph_status(uuid4(), WORKSPACE)


async def test_get_job_is_scoped_to_the_owner_and_workspace() -> None:
    store = InMemoryKGStore()
    store.add_paper()
    r = runner(store)
    job, _ = await r.start(USER, WORKSPACE)
    await finished(r)

    assert (await r.get_job(USER, WORKSPACE, job.id)).status == "completed"
    with pytest.raises(NotFoundError):
        await r.get_job(uuid4(), WORKSPACE, job.id)
    with pytest.raises(NotFoundError):
        await r.get_job(USER, uuid4(), job.id)


def job_with(status: str) -> KGJob:
    return KGJob(id=uuid4(), status=status)


def graph_row() -> KGGraph:
    return KGGraph(workspace_id=WORKSPACE, source_fingerprint="x")


@pytest.mark.parametrize(
    ("graph", "active", "last", "stale", "expected"),
    [
        (None, None, None, False, "empty"),
        (None, job_with("queued"), None, False, "queued"),
        (None, job_with("running"), None, False, "generating"),
        (graph_row, job_with("running"), None, False, "updating"),
        (graph_row, None, job_with("completed"), False, "ready"),
        (graph_row, None, job_with("completed"), True, "update_available"),
        (graph_row, None, job_with("failed"), True, "failed"),
        (None, None, job_with("failed"), False, "failed"),
    ],
)
def test_graph_state(
    graph: Callable[[], KGGraph] | None,
    active: KGJob | None,
    last: KGJob | None,
    stale: bool,
    expected: str,
) -> None:
    assert graph_state(graph() if graph else None, active, last, stale=stale) == expected


def test_fingerprint_ignores_order_but_not_papers_or_version() -> None:
    a, b = uuid4(), uuid4()

    assert source_fingerprint([a, b], VERSION) == source_fingerprint([b, a], VERSION)
    assert source_fingerprint([a], VERSION) != source_fingerprint([a, b], VERSION)
    assert source_fingerprint([a], VERSION) != source_fingerprint([a], "kg-test.v2")


def test_call_budget_raises_once_used_up() -> None:
    budget = CallBudget(2)
    budget.take()
    budget.take()

    with pytest.raises(CallBudgetExceededError):
        budget.take()
    assert budget.used == 2
