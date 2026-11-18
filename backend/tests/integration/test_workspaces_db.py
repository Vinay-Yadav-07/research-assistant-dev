"""Workspace repository SQL against a migrated database: ownership filters and D-046 deletion.

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back; the repository's commits only release a savepoint.
"""

import hashlib
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models._types import EMBEDDING_DIMENSION
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.topic_profile import TopicProfile
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.database import create_engine_from_settings
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()


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
def repo(session: AsyncSession) -> WorkspaceRepository:
    return WorkspaceRepository(session)


async def new_workspace(repo: WorkspaceRepository, user: UUID, name: str = "W") -> Workspace:
    return await repo.create(user, name=name, description=None, default_mode="corpus_only")


async def add_document(
    session: AsyncSession, user: UUID, workspaces: list[Workspace], *, chunks: int = 2
) -> Document:
    """A document linked to `workspaces`, with chunks."""
    document = Document(
        user_id=user,
        title="Paper",
        content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        storage_path=f"{user}/{uuid4()}.pdf",
    )
    session.add(document)
    await session.flush()
    for workspace in workspaces:
        session.add(WorkspaceDocument(workspace_id=workspace.id, document_id=document.id))
    for index in range(chunks):
        session.add(
            Chunk(
                document_id=document.id,
                chunk_index=index,
                page_start=1,
                page_end=1,
                text=f"chunk {index}",
                token_count=2,
                content_hash=str(index),
                embedding=[0.1] * EMBEDDING_DIMENSION,
                embedding_model="test",
            )
        )
    await session.flush()
    return document


async def count(session: AsyncSession, model: type, *conditions: object) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )


async def test_create_returns_server_defaults(repo: WorkspaceRepository) -> None:
    workspace = await new_workspace(repo, ALICE)

    assert workspace.id is not None
    assert workspace.archived is False
    assert workspace.default_mode == "corpus_only"
    assert workspace.created_at is not None


async def test_get_and_list_filter_by_owner(repo: WorkspaceRepository) -> None:
    alice_ws = await new_workspace(repo, ALICE, "Alice's")
    await new_workspace(repo, BOB, "Bob's")

    assert await repo.get(BOB, alice_ws.id) is None
    assert (await repo.get(ALICE, alice_ws.id)) is not None
    assert [w.name for w in await repo.list_owned(ALICE, limit=50, offset=0)] == ["Alice's"]


async def test_list_pages_newest_first(repo: WorkspaceRepository, session: AsyncSession) -> None:
    for seconds, name in enumerate(("first", "second", "third")):
        await new_workspace(repo, ALICE, name)
        # now() is constant inside one transaction; give each row a distinct creation time.
        await session.execute(
            Workspace.__table__.update()
            .where(Workspace.name == name, Workspace.user_id == ALICE)
            .values(created_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, seconds))
        )
    session.expire_all()

    page = await repo.list_owned(ALICE, limit=2, offset=1)

    assert [w.name for w in page] == ["second", "first"]


async def test_update_changes_only_owned(repo: WorkspaceRepository) -> None:
    workspace = await new_workspace(repo, ALICE)

    assert await repo.update(BOB, workspace.id, {"name": "Taken"}) is None
    updated = await repo.update(ALICE, workspace.id, {"name": "Renamed", "archived": True})

    assert updated is not None
    assert (updated.name, updated.archived) == ("Renamed", True)


async def test_delete_by_another_user_changes_nothing(
    repo: WorkspaceRepository, session: AsyncSession
) -> None:
    workspace = await new_workspace(repo, ALICE)
    await add_document(session, ALICE, [workspace])

    assert await repo.delete(BOB, workspace.id) is None
    assert await count(session, Workspace, Workspace.id == workspace.id) == 1
    assert await count(session, Document, Document.user_id == ALICE) == 1


async def test_delete_removes_unshared_documents_and_keeps_shared_ones(
    repo: WorkspaceRepository, session: AsyncSession
) -> None:
    doomed = await new_workspace(repo, ALICE, "doomed")
    kept = await new_workspace(repo, ALICE, "kept")
    only_here = await add_document(session, ALICE, [doomed])
    shared = await add_document(session, ALICE, [doomed, kept])
    elsewhere = await add_document(session, ALICE, [kept])
    session.add(TopicProfile(workspace_id=doomed.id, document_count=0))
    await session.flush()

    storage_paths = await repo.delete(ALICE, doomed.id)
    await repo.commit()

    assert storage_paths == [only_here.storage_path]
    assert await count(session, Workspace, Workspace.id == doomed.id) == 0
    assert await count(session, TopicProfile, TopicProfile.workspace_id == doomed.id) == 0
    assert await count(session, WorkspaceDocument, WorkspaceDocument.workspace_id == doomed.id) == 0
    assert await count(session, Document, Document.id == only_here.id) == 0
    assert await count(session, Chunk, Chunk.document_id == only_here.id) == 0
    for document in (shared, elsewhere):
        assert await count(session, Document, Document.id == document.id) == 1
        assert await count(session, Chunk, Chunk.document_id == document.id) == 2
    assert await count(session, WorkspaceDocument, WorkspaceDocument.document_id == shared.id) == 1


async def test_delete_empty_workspace_returns_no_paths(repo: WorkspaceRepository) -> None:
    workspace = await new_workspace(repo, ALICE)

    assert await repo.delete(ALICE, workspace.id) == []


async def test_workspace_reads_carry_the_keyword_summary(
    repo: WorkspaceRepository, session: AsyncSession
) -> None:
    created = await new_workspace(repo, ALICE)
    assert (created.keywords, created.summary) == (None, None)
    workspace_id = created.id
    session.add(TopicProfile(workspace_id=workspace_id, keywords=["scaffolds"], summary="S."))
    await session.flush()
    session.expire_all()

    fetched = await repo.get(ALICE, workspace_id)
    listed = await repo.list_owned(ALICE, limit=50, offset=0)
    updated = await repo.update(ALICE, workspace_id, {"name": "Renamed"})

    assert fetched is not None and updated is not None
    assert (fetched.keywords, fetched.summary) == (["scaffolds"], "S.")
    assert [w.keywords for w in listed] == [["scaffolds"]]
    assert (updated.name, updated.keywords) == ("Renamed", ["scaffolds"])
