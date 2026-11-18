"""Conversation repository SQL against a migrated database: ownership, isolation, cascades,
citation snapshots, and the all-or-nothing answer save.

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back; the service's commits and rollbacks only touch a savepoint.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.models._types import EMBEDDING_DIMENSION
from app.models.agent_run import AgentRun
from app.models.chunk import Chunk
from app.models.conversation import Approval, Citation, Claim, Conversation, Evidence, Message
from app.models.document import Document
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.conversations import ConversationRepository
from app.repositories.database import create_engine_from_settings
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.conversations import ConversationCreate
from app.services.conversations import (
    AnswerDraft,
    CitationDraft,
    ClaimDraft,
    ConversationService,
    EvidenceDraft,
    RunProgress,
    RunSummary,
)

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
CLAIM_TEXTS = ("Porosity improves infiltration.", "Stiffness matters too.")


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
def repo(session: AsyncSession) -> ConversationRepository:
    return ConversationRepository(session)


@pytest.fixture
def service(repo: ConversationRepository) -> ConversationService:
    return ConversationService(repo)


async def new_workspace(session: AsyncSession, user: UUID, mode: str = "corpus_only") -> Workspace:
    return await WorkspaceRepository(session).create(
        user, name="W", description=None, default_mode=mode
    )


async def add_document(session: AsyncSession, user: UUID, workspace: Workspace) -> Chunk:
    """A document linked to `workspace` with one chunk; returns the chunk."""
    document = Document(
        user_id=user,
        title="Scaffold porosity",
        content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
    )
    session.add(document)
    await session.flush()
    session.add(WorkspaceDocument(workspace_id=workspace.id, document_id=document.id))
    chunk = Chunk(
        document_id=document.id,
        chunk_index=0,
        page_start=3,
        page_end=4,
        section="Results",
        text="Higher porosity increased cell infiltration.",
        token_count=6,
        content_hash="0",
        embedding=[0.1] * EMBEDDING_DIMENSION,
        embedding_model="test",
    )
    session.add(chunk)
    await session.flush()
    return chunk


def draft(chunk: Chunk, *, cited_chunk_id: UUID | None = None) -> AnswerDraft:
    """An answer with one cited claim and one uncited claim."""
    return AnswerDraft(
        content="Porosity improves infiltration [1].",
        mode="corpus_only",
        claims=[
            ClaimDraft(
                text=CLAIM_TEXTS[0],
                status="supported",
                support_score=0.91,
                evidence=[EvidenceDraft(chunk_id=chunk.id, score=0.91)],
                citations=[
                    CitationDraft(
                        source_type="workspace",
                        document_id=chunk.document_id,
                        chunk_id=cited_chunk_id or chunk.id,
                        document_title="Scaffold porosity",
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        section=chunk.section,
                        quote="Higher porosity increased cell infiltration.",
                    )
                ],
            ),
            ClaimDraft(text=CLAIM_TEXTS[1], status="unsupported"),
        ],
    )


async def count(session: AsyncSession, model: type, *conditions: object) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )


async def start(
    service: ConversationService, workspace: Workspace, user: UUID = ALICE
) -> tuple[UUID, UUID]:
    """A conversation and a running QA run in it."""
    conversation = await service.create(user, workspace.id, ConversationCreate())
    run_id = await service.start_run(user, conversation.id, workflow="qa")
    return conversation.id, run_id


async def test_create_uses_the_workspace_mode_and_logs_corpus_web_approval(
    session: AsyncSession, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE, "corpus_web")

    created = await service.create(ALICE, workspace.id, ConversationCreate(title="Porosity"))

    assert created.mode == "corpus_web"
    approval = await session.scalar(select(Approval).where(Approval.conversation_id == created.id))
    assert approval is not None
    assert (approval.user_id, approval.decision, approval.run_id) == (ALICE, "corpus_web", None)
    assert approval.decided_at is not None
    assert approval.options == ["corpus_only", "corpus_web"]


async def test_reads_filter_by_owner(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, run_id = await start(service, workspace)
    answer = await service.save_answer(ALICE, conversation_id, run_id, draft(chunk), RunSummary())

    assert await repo.get_workspace(BOB, workspace.id) is None
    assert await repo.list_in_workspace(BOB, workspace.id, limit=50, offset=0) == []
    assert await repo.get(BOB, conversation_id) is None
    assert await repo.list_messages(BOB, conversation_id, limit=50, offset=0) == []
    assert await repo.get_message(BOB, answer.id) is None
    assert await repo.list_claims(BOB, answer.id) == []
    assert len(await repo.list_claims(ALICE, answer.id)) == 2


async def test_writes_into_another_users_conversation_change_nothing(
    session: AsyncSession, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    workspace_id = workspace.id
    conversation_id, run_id = await start(service, workspace)

    # A failed save rolls back, which expires loaded objects; use plain ids from here on.
    with pytest.raises(NotFoundError):
        await service.create(BOB, workspace_id, ConversationCreate())
    with pytest.raises(NotFoundError):
        await service.add_user_message(BOB, conversation_id, content="hi", mode="corpus_only")
    with pytest.raises(NotFoundError):
        await service.start_run(BOB, conversation_id, workflow="qa")
    with pytest.raises(NotFoundError):
        await service.save_answer(
            BOB, conversation_id, run_id, AnswerDraft(content="x", mode="corpus_only"), RunSummary()
        )

    assert await count(session, Conversation, Conversation.workspace_id == workspace_id) == 1
    assert await count(session, Message, Message.conversation_id == conversation_id) == 0
    assert await count(session, AgentRun, AgentRun.conversation_id == conversation_id) == 1


async def test_conversations_are_listed_per_workspace(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    first = await new_workspace(session, ALICE)
    second = await new_workspace(session, ALICE)
    in_first = await service.create(ALICE, first.id, ConversationCreate(title="first"))
    await service.create(ALICE, second.id, ConversationCreate(title="second"))

    listed = await repo.list_in_workspace(ALICE, first.id, limit=50, offset=0)

    assert [c.id for c in listed] == [in_first.id]


async def test_messages_are_paged_oldest_first(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    conversation_id, _ = await start(service, workspace)
    ids = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for minutes in (2, 0, 1):
        message = await service.add_user_message(
            ALICE, conversation_id, content=str(minutes), mode="corpus_only"
        )
        # now() is constant inside one transaction; give each row a distinct creation time.
        await session.execute(
            update(Message)
            .where(Message.id == message.id)
            .values(created_at=base + timedelta(minutes=minutes))
        )
        ids.append((minutes, message.id))
    oldest_first = [message_id for _, message_id in sorted(ids)]

    everything = await repo.list_messages(ALICE, conversation_id, limit=50, offset=0)
    page = await repo.list_messages(ALICE, conversation_id, limit=1, offset=1)

    assert [m.id for m in everything] == oldest_first
    assert [m.id for m in page] == [oldest_first[1]]


async def test_save_answer_stores_everything_and_finishes_the_run(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, run_id = await start(service, workspace)
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    )

    answer = await service.save_answer(
        ALICE,
        conversation_id,
        run_id,
        draft(chunk),
        RunSummary(latency_ms=1500, llm_calls=3, tokens=1200, trace_url="https://trace"),
    )

    claims = await repo.list_claims(ALICE, answer.id)
    assert [(c.position, c.status) for c in claims] == [(0, "supported"), (1, "unsupported")]
    assert [e.chunk_id for e in claims[0].evidence] == [chunk.id]
    [citation] = claims[0].citations
    assert (citation.document_id, citation.chunk_id) == (chunk.document_id, chunk.id)
    run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id))
    assert run is not None
    await session.refresh(run)
    assert (run.status, run.latency_ms, run.llm_calls, run.tokens) == ("completed", 1500, 3, 1200)
    assert run.finished_at is not None
    touched = await session.scalar(
        select(Conversation.updated_at).where(Conversation.id == conversation_id)
    )
    assert touched is not None and touched > datetime(2026, 1, 1, tzinfo=UTC)


async def test_failure_mid_save_leaves_nothing_behind(
    session: AsyncSession, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, run_id = await start(service, workspace)
    answer = draft(chunk, cited_chunk_id=uuid4())
    chunk_id, document_id = chunk.id, chunk.document_id

    # The run is finished and the message and claims inserted before the citation's foreign
    # key fails.
    with pytest.raises(IntegrityError):
        await service.save_answer(ALICE, conversation_id, run_id, answer, RunSummary())

    assert await count(session, Message, Message.conversation_id == conversation_id) == 0
    assert await count(session, Claim, Claim.text.in_(CLAIM_TEXTS)) == 0
    assert await count(session, Evidence, Evidence.chunk_id == chunk_id) == 0
    assert await count(session, Citation, Citation.document_id == document_id) == 0
    status = await session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))
    assert status == "running"


async def test_missing_run_leaves_nothing_behind(
    session: AsyncSession, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, _ = await start(service, workspace)

    with pytest.raises(NotFoundError):
        await service.save_answer(ALICE, conversation_id, uuid4(), draft(chunk), RunSummary())

    assert await count(session, Message, Message.conversation_id == conversation_id) == 0
    assert await count(session, Claim, Claim.text.in_(CLAIM_TEXTS)) == 0


async def test_citation_snapshot_survives_document_deletion(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, run_id = await start(service, workspace)
    answer = await service.save_answer(ALICE, conversation_id, run_id, draft(chunk), RunSummary())

    await session.execute(delete(Document).where(Document.id == chunk.document_id))
    session.expunge_all()

    claims = await repo.list_claims(ALICE, answer.id)
    [citation] = claims[0].citations
    assert (citation.document_id, citation.chunk_id) == (None, None)
    assert citation.document_title == "Scaffold porosity"
    assert (citation.page_start, citation.page_end, citation.section) == (3, 4, "Results")
    assert citation.quote == "Higher porosity increased cell infiltration."
    assert [e.chunk_id for e in claims[0].evidence] == [None]


async def test_deleting_the_workspace_removes_its_history(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE, "corpus_web")
    chunk = await add_document(session, ALICE, workspace)
    conversation_id, run_id = await start(service, workspace)
    answer = await service.save_answer(ALICE, conversation_id, run_id, draft(chunk), RunSummary())
    claim_ids = [c.id for c in await repo.list_claims(ALICE, answer.id)]

    assert await WorkspaceRepository(session).delete(ALICE, workspace.id) is not None

    assert await count(session, Conversation, Conversation.workspace_id == workspace.id) == 0
    assert await count(session, Message, Message.conversation_id == conversation_id) == 0
    assert await count(session, Claim, Claim.id.in_(claim_ids)) == 0
    assert await count(session, Evidence, Evidence.claim_id.in_(claim_ids)) == 0
    assert await count(session, Citation, Citation.claim_id.in_(claim_ids)) == 0
    assert await count(session, Approval, Approval.conversation_id == conversation_id) == 0
    assert await count(session, AgentRun, AgentRun.workspace_id == workspace.id) == 0


# --- QA run lifecycle (task #7) ---


async def paused_run(service: ConversationService, session: AsyncSession) -> tuple[UUID, UUID]:
    """A run of Alice's that waits for an approval decision; returns (conversation, run)."""
    workspace = await new_workspace(session, ALICE)
    conversation = await service.create(ALICE, workspace.id, ConversationCreate())
    started = await service.begin_run(ALICE, conversation.id, question="Why?", workflow="qa")
    await service.pause_run(
        ALICE,
        started.run_id,
        conversation.id,
        reason="Not covered.",
        options=["corpus_only", "general_knowledge"],
        progress=RunProgress(latency_ms=900, llm_calls=2, tokens=1500),
    )
    return conversation.id, started.run_id


async def test_pause_and_resume_record_the_approval_and_the_run_state(
    service: ConversationService, session: AsyncSession
) -> None:
    _, run_id = await paused_run(service, session)
    run = await session.get(AgentRun, run_id, populate_existing=True)
    assert run is not None
    assert (run.status, run.latency_ms, run.llm_calls, run.tokens) == (
        "interrupted",
        900,
        2,
        1500,
    )

    resumed = await service.resume_run(ALICE, run_id, "general_knowledge")

    assert resumed.progress == RunProgress(latency_ms=900, llm_calls=2, tokens=1500)
    approval = await session.scalar(select(Approval).where(Approval.run_id == run_id))
    assert approval is not None
    await session.refresh(approval)
    assert approval.decision == "general_knowledge"
    assert approval.decided_at is not None
    await session.refresh(run)
    assert run.status == "running"


async def test_resume_is_owner_only_once_only_and_offered_only(
    service: ConversationService, session: AsyncSession
) -> None:
    _, run_id = await paused_run(service, session)

    with pytest.raises(NotFoundError):
        await service.resume_run(BOB, run_id, "corpus_only")
    with pytest.raises(InvalidInputError):
        await service.resume_run(ALICE, run_id, "corpus_web")
    await service.resume_run(ALICE, run_id, "corpus_only")
    with pytest.raises(ConflictError):
        await service.resume_run(ALICE, run_id, "corpus_only")

    assert (
        await count(session, Approval, Approval.run_id == run_id, Approval.decision.is_(None)) == 0
    )


async def test_transition_needs_the_owner_and_the_expected_status(
    repo: ConversationRepository, service: ConversationService, session: AsyncSession
) -> None:
    _, run_id = await paused_run(service, session)

    assert not await repo.transition_run(
        BOB, run_id, from_status="interrupted", changes={"status": "running"}
    )
    assert not await repo.transition_run(
        ALICE, run_id, from_status="running", changes={"status": "completed"}
    )
    assert await repo.transition_run(
        ALICE, run_id, from_status="interrupted", changes={"status": "running"}
    )


async def test_other_users_cannot_see_or_decide_a_pending_approval(
    repo: ConversationRepository, service: ConversationService, session: AsyncSession
) -> None:
    _, run_id = await paused_run(service, session)
    approval = await repo.get_pending_approval(ALICE, run_id)
    assert approval is not None

    assert await repo.get_pending_approval(BOB, run_id) is None
    assert await repo.get_run(BOB, run_id) is None
    assert not await repo.decide_approval(BOB, approval.id, "corpus_only")
    assert await repo.decide_approval(ALICE, approval.id, "corpus_only")
    assert not await repo.decide_approval(ALICE, approval.id, "general_knowledge")


async def test_stale_sweep_fails_only_old_running_runs_not_excluded(
    service: ConversationService, session: AsyncSession
) -> None:
    workspace = await new_workspace(session, ALICE)
    conversation = await service.create(ALICE, workspace.id, ConversationCreate())
    runs = [
        (await service.begin_run(ALICE, conversation.id, question=q, workflow="qa")).run_id
        for q in ("old", "excluded", "recent", "paused")
    ]
    old, excluded, recent, paused = runs
    await session.execute(
        update(AgentRun)
        .where(AgentRun.id.in_([old, excluded, paused]))
        .values(created_at=func.now() - timedelta(hours=1))
    )
    await session.execute(
        update(AgentRun).where(AgentRun.id == paused).values(status="interrupted")
    )

    failed = await service.fail_stale_runs(
        older_than=timedelta(minutes=15), reason="restart", exclude={excluded}
    )

    # System-wide: on Supabase dev, old runs from earlier sessions may be failed too.
    assert failed >= 1
    rows = await session.execute(select(AgentRun.id, AgentRun.status).where(AgentRun.id.in_(runs)))
    statuses = {run_id: status for run_id, status in rows}
    assert statuses == {
        old: "failed",
        excluded: "running",
        recent: "running",
        paused: "interrupted",
    }


# --- reloading the history (Phase 3, p3/chat-history-api) ---


async def test_messages_saved_in_one_transaction_keep_insert_order(
    session: AsyncSession, repo: ConversationRepository, service: ConversationService
) -> None:
    # Regression: with now() every row here shared one created_at and sorted by random id.
    workspace = await new_workspace(session, ALICE)
    conversation_id, _ = await start(service, workspace)
    contents = [str(n) for n in range(10)]
    for content in contents:
        await service.add_user_message(ALICE, conversation_id, content=content, mode="corpus_only")

    messages = await repo.list_messages(ALICE, conversation_id, limit=50, offset=0)

    assert [m.content for m in messages] == contents


async def test_history_loads_each_answers_claims_and_citations(
    session: AsyncSession, service: ConversationService
) -> None:
    workspace = await new_workspace(session, ALICE)
    chunk = await add_document(session, ALICE, workspace)
    conversation = await service.create(ALICE, workspace.id, ConversationCreate())
    started = await service.begin_run(ALICE, conversation.id, question="Why?", workflow="qa")
    await service.save_answer(ALICE, conversation.id, started.run_id, draft(chunk), RunSummary())

    question, answer = await service.list_messages(ALICE, conversation.id, limit=10, offset=0)

    assert (question.role, question.run_id, question.claims) == ("user", started.run_id, [])
    assert [c.text for c in answer.claims] == list(CLAIM_TEXTS)
    [citation] = answer.claims[0].citations
    assert (citation.chunk_id, citation.page_start, citation.section) == (chunk.id, 3, "Results")
    assert [e.chunk_id for e in answer.claims[0].evidence] == [chunk.id]
    with pytest.raises(NotFoundError):
        await service.list_messages(BOB, conversation.id, limit=10, offset=0)


async def test_get_run_shows_the_pending_approval_to_the_owner_only(
    service: ConversationService, session: AsyncSession
) -> None:
    conversation_id, run_id = await paused_run(service, session)

    paused = await service.get_run(ALICE, run_id)

    assert (paused.status, paused.conversation_id) == ("interrupted", conversation_id)
    assert paused.pending_approval is not None
    assert paused.pending_approval.reason == "Not covered."
    assert paused.pending_approval.options == ["corpus_only", "general_knowledge"]
    with pytest.raises(NotFoundError):
        await service.get_run(BOB, run_id)
    await service.resume_run(ALICE, run_id, "corpus_only")
    resumed = await service.get_run(ALICE, run_id)
    assert (resumed.status, resumed.pending_approval) == ("running", None)
