"""Topic profile SQL and profile maintenance against a migrated database (S7, FR-22).

Runs in CI's pgvector container (no secrets) and against Supabase dev, inside a rolled-back
transaction.
"""

import hashlib
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import CompatibilityWarningError, NotFoundError
from app.models._types import EMBEDDING_DIMENSION
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.topic_profile import TopicProfile
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.database import create_engine_from_settings
from app.repositories.documents import DocumentRepository
from app.repositories.topic_profiles import (
    ProfileState,
    SummaryDocument,
    TopicProfileRepository,
)
from app.services.documents import DocumentService
from app.services.topic_profile import CompatibilityOptions, TopicProfileService

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
OPTIONS = CompatibilityOptions(first_chunks=2, max_pages=3, threshold=0.5)


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
def repo(session: AsyncSession) -> TopicProfileRepository:
    return TopicProfileRepository(session)


def vector(*weights: tuple[int, float]) -> list[float]:
    """A vector that is zero except at the given (index, value) positions."""
    values = [0.0] * EMBEDDING_DIMENSION
    for index, value in weights:
        values[index] = value
    return values


X = vector((0, 1.0))
Y = vector((1, 1.0))


async def workspace(session: AsyncSession, user: UUID) -> UUID:
    row = Workspace(user_id=user, name="W")
    session.add(row)
    await session.flush()
    return row.id


async def document(
    session: AsyncSession,
    user: UUID,
    workspace_ids: list[UUID],
    embeddings: list[list[float]],
    *,
    status: str = "ready",
) -> UUID:
    """A document linked to `workspace_ids` with one chunk per embedding, in order."""
    row = Document(
        user_id=user, content_hash=hashlib.sha256(uuid4().bytes).hexdigest(), status=status
    )
    session.add(row)
    await session.flush()
    for workspace_id in workspace_ids:
        session.add(WorkspaceDocument(workspace_id=workspace_id, document_id=row.id))
    session.add_all(
        Chunk(
            document_id=row.id,
            chunk_index=index,
            page_start=1,
            page_end=1,
            text=f"chunk {index}",
            token_count=2,
            content_hash=str(index),
            embedding=embedding,
            embedding_model="test-model",
        )
        for index, embedding in enumerate(embeddings)
    )
    await session.flush()
    return row.id


def document_service(session: AsyncSession) -> DocumentService:
    return DocumentService(
        DocumentRepository(session),
        None,
        lambda _user, _document, _data: None,
        profiles=TopicProfileService(TopicProfileRepository(session), OPTIONS),
        signed_url_ttl_seconds=60,
    )


async def test_document_vector_averages_the_first_chunks_in_order(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    # Inserted out of order: the mean must use chunk_index 0 and 1, not 2.
    document_id = await document(session, ALICE, [], [X, Y, vector((2, 1.0))])

    mean = await repo.document_vector(ALICE, document_id, first_chunks=2)

    assert mean is not None
    assert mean[:3] == pytest.approx([0.5, 0.5, 0.0])


async def test_document_vector_is_owner_only_and_none_without_chunks(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    with_chunks = await document(session, ALICE, [], [X])
    without = await document(session, ALICE, [], [])

    assert await repo.document_vector(BOB, with_chunks, first_chunks=2) is None
    assert await repo.document_vector(ALICE, without, first_chunks=2) is None


async def test_get_and_lock_are_owner_only(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    alice_ws = await workspace(session, ALICE)

    assert await repo.get(ALICE, alice_ws) == ProfileState(centroid=None, document_count=0)
    assert await repo.get(BOB, alice_ws) is None
    assert await repo.lock(BOB, alice_ws) is None
    assert await session.get(TopicProfile, alice_ws) is None

    assert await repo.lock(ALICE, alice_ws) == ProfileState(centroid=None, document_count=0)
    assert await session.get(TopicProfile, alice_ws) is not None


async def test_save_round_trips(session: AsyncSession, repo: TopicProfileRepository) -> None:
    alice_ws = await workspace(session, ALICE)
    await repo.lock(ALICE, alice_ws)

    await repo.save(alice_ws, ProfileState(centroid=X, document_count=3))

    state = await repo.get(ALICE, alice_ws)
    assert state is not None
    assert state.document_count == 3
    assert state.centroid == pytest.approx(X)


async def test_linked_workspaces_are_the_owners(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    first, second = await workspace(session, ALICE), await workspace(session, ALICE)
    document_id = await document(session, ALICE, [first, second], [X])

    assert await repo.linked_workspaces(ALICE, document_id) == sorted([first, second])
    assert await repo.linked_workspaces(BOB, document_id) == []


async def test_ready_document_joins_and_leaves_the_profile(session: AsyncSession) -> None:
    alice_ws = await workspace(session, ALICE)
    first = await document(session, ALICE, [alice_ws], [X])
    second = await document(session, ALICE, [alice_ws], [vector((0, 1.0), (1, 1.0))])
    profiles = TopicProfileService(TopicProfileRepository(session), OPTIONS)
    repo = TopicProfileRepository(session)

    await profiles.document_ready(ALICE, first)
    await profiles.document_ready(ALICE, second)

    state = await repo.get(ALICE, alice_ws)
    assert state is not None and state.document_count == 2
    score = await session.scalar(
        select(WorkspaceDocument.compatibility_score).where(
            WorkspaceDocument.workspace_id == alice_ws, WorkspaceDocument.document_id == second
        )
    )
    assert score == pytest.approx(2**-0.5)

    await document_service(session).remove(ALICE, alice_ws, second)

    state = await repo.get(ALICE, alice_ws)
    assert state is not None and state.document_count == 1
    assert state.centroid == pytest.approx(X, abs=1e-6)


async def test_link_warns_then_overrides(session: AsyncSession) -> None:
    source, target = await workspace(session, ALICE), await workspace(session, ALICE)
    on_topic = await document(session, ALICE, [target], [X])
    unrelated = await document(session, ALICE, [source], [Y])
    await TopicProfileService(TopicProfileRepository(session), OPTIONS).document_ready(
        ALICE, on_topic
    )
    service = document_service(session)

    with pytest.raises(CompatibilityWarningError):
        await service.link(ALICE, target, unrelated)
    assert await session.get(WorkspaceDocument, (target, unrelated)) is None
    await service.link(ALICE, target, unrelated, override=True)

    link = await session.get(WorkspaceDocument, (target, unrelated))
    assert link is not None
    assert link.override is True
    assert link.compatibility_score == pytest.approx(0.0)
    state = await TopicProfileRepository(session).get(ALICE, target)
    assert state is not None and state.document_count == 2


async def test_other_users_cannot_touch_a_profile_through_link_or_remove(
    session: AsyncSession,
) -> None:
    alice_ws = await workspace(session, ALICE)
    document_id = await document(session, ALICE, [alice_ws], [X])
    await TopicProfileService(TopicProfileRepository(session), OPTIONS).document_ready(
        ALICE, document_id
    )
    bob_ws = await workspace(session, BOB)
    service = document_service(session)

    for call in (
        service.link(BOB, alice_ws, document_id),
        service.link(BOB, bob_ws, document_id),
        service.remove(BOB, alice_ws, document_id),
    ):
        with pytest.raises(NotFoundError):
            await call

    state = await TopicProfileRepository(session).get(ALICE, alice_ws)
    assert state is not None and state.document_count == 1
    assert await TopicProfileRepository(session).get(BOB, bob_ws) == ProfileState(None, 0)


# --- Keyword summary (S7, D-068) ---


async def test_summary_documents_are_ready_owned_first_chunks_newest_first(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    alice_ws = await workspace(session, ALICE)
    older = await document(session, ALICE, [alice_ws], [X, Y])
    newer = await document(session, ALICE, [alice_ws], [Y])
    await document(session, ALICE, [alice_ws], [X], status="embedding")
    await document(session, ALICE, [await workspace(session, ALICE)], [X])
    for seconds, document_id in enumerate((older, newer)):
        # now() is constant inside one transaction; give each link a distinct time.
        await session.execute(
            update(WorkspaceDocument)
            .where(WorkspaceDocument.document_id == document_id)
            .values(added_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, seconds))
        )
    await session.execute(update(Document).where(Document.id == older).values(title="Older paper"))

    documents = await repo.summary_documents(ALICE, alice_ws, limit=10)

    assert documents == [
        SummaryDocument(title=None, text="chunk 0"),
        SummaryDocument(title="Older paper", text="chunk 0"),
    ]
    assert await repo.summary_documents(ALICE, alice_ws, limit=1) == documents[:1]


async def test_summary_documents_are_none_for_another_users_workspace(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    alice_ws = await workspace(session, ALICE)
    await document(session, ALICE, [alice_ws], [X])

    assert await repo.summary_documents(BOB, alice_ws, limit=10) is None
    assert await repo.summary_documents(ALICE, await workspace(session, ALICE), limit=10) == []


async def test_save_summary_is_owner_only(
    session: AsyncSession, repo: TopicProfileRepository
) -> None:
    alice_ws = await workspace(session, ALICE)
    await repo.lock(ALICE, alice_ws)

    await repo.save_summary(BOB, alice_ws, keywords=["stolen"], summary="Bob's.")
    profile = await session.get(TopicProfile, alice_ws)
    assert profile is not None
    await session.refresh(profile)
    assert (profile.keywords, profile.summary) == (None, None)

    await repo.save_summary(ALICE, alice_ws, keywords=["scaffolds"], summary="Alice's.")
    await session.refresh(profile)
    assert (profile.keywords, profile.summary) == (["scaffolds"], "Alice's.")
