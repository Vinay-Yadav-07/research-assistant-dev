"""Knowledge graph repository SQL against a migrated database: one active job per workspace,
ownership and workspace scoping, idempotent per-paper extractions, cascades, and the
heartbeat-based sweep (SRS §9.1, D-081).

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back.
"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models._types import EMBEDDING_DIMENSION
from app.models.knowledge_graph import (
    KGDocumentExtraction,
    KGEntityMention,
    KGJob,
    KGNode,
    KGRelationMention,
)
from app.models.workspace import Workspace
from app.repositories.database import create_engine_from_settings
from app.repositories.documents import DocumentFields, DocumentRepository, NewChunk
from app.repositories.knowledge_graph import (
    JobUsage,
    KnowledgeGraphRepository,
    NewEntityMention,
    NewRelationMention,
    PaperExtraction,
)
from app.services.documents import storage_path_for
from app.services.knowledge_graph_build import KnowledgeGraphBuilder
from app.services.knowledge_graph_jobs import source_fingerprint

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
VERSION = "kg-test.v1"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    engine = create_engine_from_settings(Settings())
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as db:
                    yield db
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> KnowledgeGraphRepository:
    return KnowledgeGraphRepository(session)


async def workspace(session: AsyncSession, user: UUID) -> UUID:
    row = Workspace(user_id=user, name="W")
    session.add(row)
    await session.flush()
    return row.id


async def ready_paper(session: AsyncSession, user: UUID, workspace_ids: list[UUID]) -> UUID:
    documents = DocumentRepository(session)
    document_id = uuid4()
    created = await documents.create(
        user,
        document_id,
        content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        storage_path=storage_path_for(user, document_id),
    )
    assert created is not None
    for workspace_id in workspace_ids:
        await documents.link(workspace_id, document_id)
    chunks = [
        NewChunk(
            chunk_index=index,
            page_start=index + 1,
            page_end=index + 1,
            section="Results",
            text=f"LSTM was evaluated on the M4 dataset ({index}).",
            token_count=10,
            content_hash=str(index),
            embedding=[0.1] * EMBEDDING_DIMENSION,
            embedding_model="test-model",
        )
        for index in range(2)
    ]
    fields = DocumentFields(
        title="Paper", authors=[], year=None, venue=None, doi=None, page_count=2
    )
    await documents.complete(user, document_id, fields, chunks)
    await session.flush()
    return document_id


async def new_job(repo: KnowledgeGraphRepository, user: UUID, workspace_id: UUID) -> KGJob | None:
    return await repo.create_job(
        user, workspace_id, kind="generate", extractor_version=VERSION, call_budget=10
    )


async def extraction_for(
    repo: KnowledgeGraphRepository, user: UUID, document_id: UUID
) -> PaperExtraction:
    [first, second] = await repo.document_chunks(user, document_id)
    return PaperExtraction(
        chunks_considered=2,
        entities=[
            NewEntityMention("m", first.chunk_id, "method", "LSTM", "lstm", first.text),
            NewEntityMention(
                "d", first.chunk_id, "dataset", "M4 dataset", "m4 dataset", first.text
            ),
        ],
        relations=[NewRelationMention(first.chunk_id, "m", "d", "evaluated_on", first.text, 0.97)],
        rejected_counts={"not_in_quote": 1},
    )


async def count(session: AsyncSession, model: type[object]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_a_workspace_has_at_most_one_active_job(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    other = await workspace(session, ALICE)

    first = await new_job(repo, ALICE, ws)
    assert first is not None
    assert await new_job(repo, ALICE, ws) is None
    assert await new_job(repo, ALICE, other) is not None
    active = await repo.active_job(ALICE, ws)
    assert active is not None and active.id == first.id

    await repo.finish_job(ALICE, first.id, status="completed", usage=JobUsage(llm_calls=3))
    # One transaction gives both jobs the same now(); requests are separate transactions.
    await session.execute(
        update(KGJob)
        .where(KGJob.id == first.id)
        .values(created_at=func.now() - timedelta(minutes=1))
    )
    second = await new_job(repo, ALICE, ws)
    assert second is not None
    latest = await repo.latest_job(ALICE, ws)
    assert latest is not None and latest.id == second.id


async def test_the_active_job_index_rejects_a_direct_second_insert(
    session: AsyncSession,
) -> None:
    ws = await workspace(session, ALICE)
    for _ in range(2):
        session.add(
            KGJob(
                user_id=ALICE,
                workspace_id=ws,
                kind="generate",
                call_budget=1,
                extractor_version=VERSION,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_jobs_and_graph_reads_are_scoped_to_the_owner(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    job = await new_job(repo, ALICE, ws)
    assert job is not None

    assert await repo.workspace_owned(ALICE, ws)
    assert not await repo.workspace_owned(BOB, ws)
    assert await repo.get_job(BOB, ws, job.id) is None
    assert await repo.get_job(ALICE, uuid4(), job.id) is None
    assert await repo.active_job(BOB, ws) is None
    assert await repo.latest_job(BOB, ws) is None
    assert await repo.graph(ALICE, ws) is None


async def test_ready_and_pending_documents_follow_links_status_and_extractions(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    other = await workspace(session, ALICE)
    first = await ready_paper(session, ALICE, [ws])
    second = await ready_paper(session, ALICE, [ws, other])
    await ready_paper(session, ALICE, [other])
    queued = uuid4()
    await DocumentRepository(session).create(ALICE, queued, content_hash="queued", storage_path="x")
    await DocumentRepository(session).link(ws, queued)

    assert await repo.ready_document_ids(ALICE, ws) == sorted([first, second])
    assert await repo.ready_document_ids(BOB, ws) == []
    # Linked in one transaction, so `added_at` ties; compare as sets.
    assert set(await repo.pending_document_ids(ALICE, ws, VERSION)) == {first, second}

    # One extraction serves every workspace of the owner that links the paper.
    assert await repo.save_extraction(
        ALICE, second, VERSION, await extraction_for(repo, ALICE, second), llm_calls=2, tokens=50
    )
    assert await repo.pending_document_ids(ALICE, ws, VERSION) == [first]
    assert second not in await repo.pending_document_ids(ALICE, other, VERSION)
    assert set(await repo.pending_document_ids(ALICE, ws, "kg-test.v2")) == {first, second}


async def test_save_extraction_stores_mentions_once_and_cascades_with_the_document(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    paper = await ready_paper(session, ALICE, [ws])
    extraction = await extraction_for(repo, ALICE, paper)

    assert await repo.save_extraction(ALICE, paper, VERSION, extraction, llm_calls=2, tokens=50)
    assert await repo.save_extraction(ALICE, paper, VERSION, extraction, llm_calls=9, tokens=99)

    stored = await session.scalar(select(KGDocumentExtraction))
    assert stored is not None
    assert (stored.llm_calls, stored.rejected_counts) == (2, {"not_in_quote": 1})
    assert await count(session, KGEntityMention) == 2
    relation = await session.scalar(select(KGRelationMention))
    assert relation is not None and relation.relation_type == "evaluated_on"

    found, _ = await DocumentRepository(session).unlink(ALICE, ws, paper)
    await session.flush()
    assert found
    for model in (KGDocumentExtraction, KGEntityMention, KGRelationMention):
        assert await count(session, model) == 0


async def test_save_extraction_refuses_other_users_and_other_documents_chunks(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    paper = await ready_paper(session, ALICE, [ws])
    other_paper = await ready_paper(session, ALICE, [ws])
    extraction = await extraction_for(repo, ALICE, paper)

    assert not await repo.save_extraction(BOB, paper, VERSION, extraction, llm_calls=1, tokens=1)
    assert await repo.document_chunks(BOB, paper) == []
    with pytest.raises(ValueError):
        await repo.save_extraction(ALICE, other_paper, VERSION, extraction, llm_calls=1, tokens=1)
    assert await count(session, KGDocumentExtraction) == 0


async def test_progress_heartbeat_and_finish_are_recorded(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    paper = await ready_paper(session, ALICE, [ws])
    job = await new_job(repo, ALICE, ws)
    assert job is not None

    await repo.start_job(ALICE, job.id, documents_total=1)
    await repo.record_progress(
        ALICE, job.id, documents_done=0, current_document_id=paper, usage=JobUsage(2, 30, 5)
    )
    await repo.finish_job(
        ALICE,
        job.id,
        status="failed",
        usage=JobUsage(4, 60, 10),
        error_code="llm_quota_exhausted",
        error_message="Quota.",
    )

    read = await repo.get_job(ALICE, ws, job.id)
    assert read is not None
    assert (read.status, read.phase, read.documents_total) == ("failed", "extracting", 1)
    assert (read.llm_calls, read.input_tokens, read.output_tokens) == (4, 60, 10)
    assert (read.error_code, read.current_document_id) == ("llm_quota_exhausted", None)
    assert read.started_at is not None and read.finished_at is not None


async def test_the_sweep_fails_only_active_jobs_with_a_stale_heartbeat(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    jobs = []
    for _ in range(4):
        job = await new_job(repo, ALICE, await workspace(session, ALICE))
        assert job is not None
        jobs.append(job)
    stale, fresh, excluded, finished = jobs
    old = func.now() - timedelta(hours=1)
    await session.execute(
        update(KGJob)
        .where(KGJob.id.in_([stale.id, excluded.id, finished.id]))
        .values(heartbeat_at=old)
    )
    await repo.finish_job(ALICE, finished.id, status="completed", usage=JobUsage())
    await repo.heartbeat(ALICE, fresh.id)

    swept = await repo.fail_stale_jobs(
        older_than=timedelta(minutes=10),
        error_code="interrupted",
        error_message="Interrupted.",
        exclude={excluded.id},
    )

    assert swept == 1

    async def status(job: KGJob) -> tuple[str, str | None]:
        read = await repo.get_job(ALICE, job.workspace_id, job.id)
        assert read is not None
        return read.status, read.error_code

    assert await status(stale) == ("failed", "interrupted")
    assert await status(fresh) == ("queued", None)
    assert await status(excluded) == ("queued", None)
    assert await status(finished) == ("completed", None)


async def test_deleting_the_workspace_deletes_its_jobs(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    assert await new_job(repo, ALICE, ws) is not None

    await session.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": ws})
    assert await count(session, KGJob) == 0


def builder_on(session: AsyncSession) -> KnowledgeGraphBuilder:
    @asynccontextmanager
    async def open_store() -> AsyncIterator[KnowledgeGraphRepository]:
        yield KnowledgeGraphRepository(session)

    return KnowledgeGraphBuilder(open_store, VERSION)


async def paper_with_graph(
    session: AsyncSession, repo: KnowledgeGraphRepository, workspace_ids: list[UUID]
) -> UUID:
    """A ready paper whose extraction states "LSTM is evaluated on the M4 dataset"."""
    paper = await ready_paper(session, ALICE, workspace_ids)
    assert await repo.save_extraction(
        ALICE, paper, VERSION, await extraction_for(repo, ALICE, paper), llm_calls=1, tokens=10
    )
    return paper


async def built_job(repo: KnowledgeGraphRepository, workspace_id: UUID) -> UUID:
    """A finished job to credit a build to (one active job per workspace)."""
    job = await new_job(repo, ALICE, workspace_id)
    assert job is not None
    await repo.finish_job(ALICE, job.id, status="completed", usage=JobUsage())
    return job.id


async def test_the_build_merges_papers_and_counts_live_support(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    first = await paper_with_graph(session, repo, [ws])
    await paper_with_graph(session, repo, [ws])

    await builder_on(session).build(ALICE, ws, await built_job(repo, ws))

    nodes, edges, truncated = await repo.graph_view(ALICE, ws, max_nodes=10)
    assert not truncated
    assert {(n.label, n.document_count, n.mention_count) for n in nodes} == {
        ("LSTM", 2, 2),
        ("M4 dataset", 2, 2),
    }
    (edge,) = edges
    assert (edge.relation_type, edge.document_count, edge.mention_count) == ("evaluated_on", 2, 2)
    graph = await repo.graph(ALICE, ws)
    assert graph is not None
    assert (graph.node_count, graph.edge_count) == (2, 1)
    assert graph.source_fingerprint == source_fingerprint(
        await repo.ready_document_ids(ALICE, ws), VERSION
    )

    lstm = next(n for n in nodes if n.label == "LSTM")
    evidence = await repo.node_evidence(ALICE, ws, lstm.id, limit=10, offset=0)
    assert evidence is not None and len(evidence) == 2
    assert {row.page_start for row in evidence} == {1}
    assert all("LSTM" in row.quote for row in evidence)
    assert await repo.node_evidence(BOB, ws, lstm.id, limit=10, offset=0) is None
    assert (
        await repo.edge_evidence(
            ALICE, await workspace(session, ALICE), edge.id, limit=10, offset=0
        )
        is None
    )

    # Removing a paper hides its evidence at once and keeps what the other paper supports.
    found, _ = await DocumentRepository(session).unlink(ALICE, ws, first)
    assert found
    nodes, edges, _ = await repo.graph_view(ALICE, ws, max_nodes=10)
    assert {(n.label, n.document_count) for n in nodes} == {("LSTM", 1), ("M4 dataset", 1)}
    assert [(e.relation_type, e.document_count) for e in edges] == [("evaluated_on", 1)]


async def test_a_paper_removed_from_one_workspace_stays_in_the_other(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws, other = await workspace(session, ALICE), await workspace(session, ALICE)
    shared = await paper_with_graph(session, repo, [ws, other])
    for workspace_id in (ws, other):
        await builder_on(session).build(ALICE, workspace_id, await built_job(repo, workspace_id))

    found, deleted_path = await DocumentRepository(session).unlink(ALICE, ws, shared)

    assert found and deleted_path is None
    assert (await repo.graph_view(ALICE, ws, max_nodes=10))[0] == []
    nodes, edges, _ = await repo.graph_view(ALICE, other, max_nodes=10)
    assert len(nodes) == 2 and len(edges) == 1
    assert await repo.graph_view(BOB, other, max_nodes=10) == ([], [], False)


async def test_a_rebuild_replaces_the_graph_and_a_failed_one_keeps_it(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    await paper_with_graph(session, repo, [ws])
    builder = builder_on(session)
    await builder.build(ALICE, ws, await built_job(repo, ws))
    before, _, _ = await repo.graph_view(ALICE, ws, max_nodes=10)

    await builder.build(ALICE, ws, await built_job(repo, ws))
    after, _, _ = await repo.graph_view(ALICE, ws, max_nodes=10)
    assert {n.label for n in after} == {n.label for n in before}
    assert {n.id for n in after}.isdisjoint({n.id for n in before})
    assert await count(session, KGNode) == 2

    failing_job = await built_job(repo, ws)
    with pytest.raises(RuntimeError):
        async with session.begin_nested():
            await repo.replace_graph(
                ALICE, ws, job_id=failing_job, source_fingerprint="x", nodes=[], edges=[]
            )
            raise RuntimeError("build failed halfway")
    kept, _, _ = await repo.graph_view(ALICE, ws, max_nodes=10)
    assert {n.id for n in kept} == {n.id for n in after}


async def test_another_user_cannot_replace_a_graph(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    await paper_with_graph(session, repo, [ws])
    await builder_on(session).build(ALICE, ws, await built_job(repo, ws))

    await repo.replace_graph(BOB, ws, job_id=uuid4(), source_fingerprint="x", nodes=[], edges=[])

    assert len((await repo.graph_view(ALICE, ws, max_nodes=10))[0]) == 2


async def test_the_node_cap_reports_truncation(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    await paper_with_graph(session, repo, [ws])
    await builder_on(session).build(ALICE, ws, await built_job(repo, ws))

    nodes, edges, truncated = await repo.graph_view(ALICE, ws, max_nodes=1)

    assert len(nodes) == 1 and truncated
    assert edges == []


async def test_a_failed_extraction_is_replaced_by_a_later_one(
    session: AsyncSession, repo: KnowledgeGraphRepository
) -> None:
    ws = await workspace(session, ALICE)
    paper = await ready_paper(session, ALICE, [ws])
    failed = PaperExtraction(chunks_considered=2, status="failed")

    assert await repo.save_extraction(ALICE, paper, VERSION, failed, llm_calls=2, tokens=9)
    assert await repo.pending_document_ids(ALICE, ws, VERSION) == [paper]
    assert await repo.save_extraction(
        ALICE, paper, VERSION, await extraction_for(repo, ALICE, paper), llm_calls=3, tokens=30
    )

    stored = await session.scalar(
        select(KGDocumentExtraction).execution_options(populate_existing=True)
    )
    assert stored is not None and (stored.status, stored.llm_calls) == ("completed", 3)
    assert await count(session, KGEntityMention) == 2
    assert await repo.pending_document_ids(ALICE, ws, VERSION) == []
