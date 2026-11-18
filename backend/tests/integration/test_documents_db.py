"""Document repository SQL against a migrated database: ownership, unique content hash, the
D-046 removal rule, chunk storage, the stale-ingestion sweep, and the duplicate-upload race.

Runs in CI's pgvector container (no secrets) and against Supabase dev. Tests run in a
rolled-back transaction, except the race test, which commits and cleans up after itself.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models._types import EMBEDDING_DIMENSION
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.workspace import Workspace
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import DocumentFields, DocumentRepository, NewChunk
from app.repositories.topic_profiles import TopicProfileRepository
from app.services.documents import DocumentService, storage_path_for
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from tests.unit.storage_fakes import InMemoryFileStorage

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
PDF = b"%PDF-fake\n# Results\nPorous scaffolds."


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine_from_settings(Settings())
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            ) as db:
                yield db
        finally:
            await transaction.rollback()


@pytest.fixture
def repo(session: AsyncSession) -> DocumentRepository:
    return DocumentRepository(session)


async def workspace(session: AsyncSession, user: UUID) -> UUID:
    row = Workspace(user_id=user, name="W")
    session.add(row)
    await session.flush()
    return row.id


async def document(
    repo: DocumentRepository, user: UUID, workspace_ids: list[UUID], data: bytes | None = None
) -> Document:
    document_id = uuid4()
    content = data or uuid4().bytes
    created = await repo.create(
        user,
        document_id,
        content_hash=hashlib.sha256(content).hexdigest(),
        storage_path=storage_path_for(user, document_id),
    )
    assert created is not None
    for workspace_id in workspace_ids:
        await repo.link(workspace_id, document_id)
    return created


def new_chunk(index: int) -> NewChunk:
    return NewChunk(
        chunk_index=index,
        page_start=1,
        page_end=2,
        section="Results",
        text=f"chunk {index}",
        token_count=2,
        content_hash=str(index),
        embedding=[0.1] * EMBEDDING_DIMENSION,
        embedding_model="test-model",
    )


async def test_create_starts_uploaded(repo: DocumentRepository) -> None:
    created = await document(repo, ALICE, [])

    assert created.status == "uploaded"
    assert created.source == "upload"
    assert created.storage_path == f"{ALICE}/{created.id}.pdf"


async def test_same_file_twice_for_one_user_is_refused(repo: DocumentRepository) -> None:
    await document(repo, ALICE, [], data=PDF)
    content_hash = hashlib.sha256(PDF).hexdigest()

    again = await repo.create(ALICE, uuid4(), content_hash=content_hash, storage_path="x")
    for_bob = await repo.create(BOB, uuid4(), content_hash=content_hash, storage_path="y")

    assert again is None
    assert for_bob is not None


async def test_reads_filter_by_owner(repo: DocumentRepository, session: AsyncSession) -> None:
    alice_ws = await workspace(session, ALICE)
    created = await document(repo, ALICE, [alice_ws], data=PDF)
    content_hash = hashlib.sha256(PDF).hexdigest()

    assert await repo.get(BOB, created.id) is None
    assert await repo.find_by_hash(BOB, content_hash) is None
    assert await repo.list_in_workspace(BOB, alice_ws, limit=50, offset=0) == []
    assert await repo.is_linked(BOB, alice_ws, created.id) is False
    assert await repo.workspace_owned(BOB, alice_ws) is False
    assert await repo.get(ALICE, created.id) is not None
    assert await repo.find_by_hash(ALICE, content_hash) is not None
    assert [d.id for d in await repo.list_in_workspace(ALICE, alice_ws, limit=50, offset=0)] == [
        created.id
    ]
    assert await repo.is_linked(ALICE, alice_ws, created.id) is True
    assert await repo.workspace_owned(ALICE, alice_ws) is True


async def test_list_shows_only_the_workspaces_documents(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    first, second = await workspace(session, ALICE), await workspace(session, ALICE)
    in_first = await document(repo, ALICE, [first])
    await document(repo, ALICE, [second])

    listed = await repo.list_in_workspace(ALICE, first, limit=50, offset=0)

    assert [d.id for d in listed] == [in_first.id]


async def test_unlink_is_owner_only(repo: DocumentRepository, session: AsyncSession) -> None:
    alice_ws = await workspace(session, ALICE)
    created = await document(repo, ALICE, [alice_ws])

    assert await repo.unlink(BOB, alice_ws, created.id) == (False, None)
    assert await repo.is_linked(ALICE, alice_ws, created.id) is True


async def test_unlink_shared_document_keeps_it(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    first, second = await workspace(session, ALICE), await workspace(session, ALICE)
    created = await document(repo, ALICE, [first, second])

    assert await repo.unlink(ALICE, first, created.id) == (True, None)
    assert await repo.get(ALICE, created.id) is not None
    assert await repo.is_linked(ALICE, second, created.id) is True


async def test_unlink_last_link_deletes_document_and_chunks(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    alice_ws = await workspace(session, ALICE)
    created = await document(repo, ALICE, [alice_ws])
    await repo.complete(ALICE, created.id, fields(), [new_chunk(0), new_chunk(1)])

    found, path = await repo.unlink(ALICE, alice_ws, created.id)

    assert (found, path) == (True, f"{ALICE}/{created.id}.pdf")
    session.expire_all()
    assert await repo.get(ALICE, created.id) is None
    chunks = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == created.id)
    )
    assert chunks == 0


def fields() -> DocumentFields:
    return DocumentFields(
        title="Scaffolds", authors=["A. B"], year=2024, venue="J", doi="10.1/x", page_count=2
    )


async def test_complete_stores_chunks_and_metadata(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    created = await document(repo, ALICE, [])
    assert await repo.lock(ALICE, created.id) is True

    document_id = created.id
    await repo.complete(ALICE, document_id, fields(), [new_chunk(0), new_chunk(1)])

    session.expire_all()
    stored = await repo.get(ALICE, document_id)
    assert stored is not None
    assert (stored.status, stored.title, stored.authors, stored.page_count) == (
        "ready",
        "Scaffolds",
        ["A. B"],
        2,
    )
    chunks = list(await session.scalars(select(Chunk).where(Chunk.document_id == document_id)))
    assert sorted(chunk.chunk_index for chunk in chunks) == [0, 1]
    assert {chunk.embedding_model for chunk in chunks} == {"test-model"}


async def test_status_changes_are_owner_only(repo: DocumentRepository) -> None:
    created = await document(repo, ALICE, [])

    assert await repo.set_status(BOB, created.id, "failed", error="x") is False
    assert await repo.lock(BOB, created.id) is False
    assert await repo.set_status(ALICE, created.id, "parsing") is True
    assert await repo.set_status(ALICE, uuid4(), "parsing") is False


async def test_restart_only_restarts_failed_documents(repo: DocumentRepository) -> None:
    created = await document(repo, ALICE, [])

    assert await repo.restart(ALICE, created.id) is None
    await repo.set_status(ALICE, created.id, "failed", error="unreadable")
    assert await repo.restart(BOB, created.id) is None
    restarted = await repo.restart(ALICE, created.id)

    assert restarted is not None
    assert (restarted.status, restarted.error) == ("uploaded", None)


async def test_fail_stale_fails_only_old_in_progress_documents(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    old_parsing = await document(repo, ALICE, [])
    old_uploaded = await document(repo, ALICE, [])
    recent_embedding = await document(repo, ALICE, [])
    old_ready = await document(repo, BOB, [])
    ages = {
        old_parsing.id: ("parsing", 20),
        old_uploaded.id: ("uploaded", 16),
        recent_embedding.id: ("embedding", 14),
        old_ready.id: ("ready", 60),
    }
    for document_id, (status, minutes) in ages.items():
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=status, updated_at=func.now() - timedelta(minutes=minutes))
        )

    count = await repo.fail_stale(older_than=timedelta(minutes=15), reason="interrupted")

    assert count >= 2  # other stale rows in a shared dev database may be included
    session.expire_all()
    statuses = {document_id: (await session.get(Document, document_id)) for document_id in ages}
    assert {k: (v.status, v.error) for k, v in statuses.items() if v is not None} == {
        old_parsing.id: ("failed", "interrupted"),
        old_uploaded.id: ("failed", "interrupted"),
        recent_embedding.id: ("embedding", None),
        old_ready.id: ("ready", None),
    }


async def test_fail_stale_skips_excluded_documents(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    queued = await document(repo, ALICE, [])
    orphaned = await document(repo, ALICE, [])
    queued_id, orphaned_id = queued.id, orphaned.id
    await session.execute(
        update(Document)
        .where(Document.id.in_([queued_id, orphaned_id]))
        .values(updated_at=func.now() - timedelta(minutes=30))
    )

    await repo.fail_stale(older_than=timedelta(minutes=15), reason="stuck", exclude={queued_id})

    rows = dict(
        (
            await session.execute(
                select(Document.id, Document.status).where(
                    Document.id.in_([queued_id, orphaned_id])
                )
            )
        ).all()
    )
    assert rows == {queued_id: "uploaded", orphaned_id: "failed"}


async def test_status_change_bumps_updated_at(
    repo: DocumentRepository, session: AsyncSession
) -> None:
    created = await document(repo, ALICE, [])
    await session.execute(
        update(Document)
        .where(Document.id == created.id)
        .values(updated_at=func.now() - timedelta(hours=1))
    )

    await repo.set_status(ALICE, created.id, "parsing")

    age = await session.scalar(
        select(func.now() - Document.updated_at).where(Document.id == created.id)
    )
    assert age is not None and age < timedelta(minutes=1)


class SlowStorage(InMemoryFileStorage):
    """Holds the first upload's transaction open while the second upload runs."""

    async def upload_pdf(self, path: str, data: bytes) -> None:
        await asyncio.sleep(0.5)
        await super().upload_pdf(path, data)


async def test_concurrent_uploads_of_the_same_file_make_one_document(engine: AsyncEngine) -> None:
    sessions: async_sessionmaker[AsyncSession] = create_sessionmaker(engine)
    user = uuid4()
    storage = SlowStorage()
    scheduled: list[UUID] = []

    async with sessions() as setup:
        workspace_id = await workspace(setup, user)
        await setup.commit()

    async def upload() -> tuple[bool, UUID]:
        async with sessions() as session:
            service = DocumentService(
                DocumentRepository(session),
                storage,
                lambda _user, document_id, _data: scheduled.append(document_id),
                profiles=TopicProfileService(
                    TopicProfileRepository(session), CompatibilityOptions.from_settings(Settings())
                ),
                signed_url_ttl_seconds=60,
            )
            result = await service.upload(user, workspace_id, PDF)
            return result.duplicate, result.document.id

    try:
        first, second = await asyncio.gather(upload(), upload())

        assert sorted([first[0], second[0]]) == [False, True]
        assert first[1] == second[1]
        assert len(scheduled) == 1
        assert len(storage.objects) == 1
        async with sessions() as check:
            rows = await check.scalar(
                select(func.count()).select_from(Document).where(Document.user_id == user)
            )
        assert rows == 1
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Document).where(Document.user_id == user))
            await cleanup.execute(delete(Workspace).where(Workspace.user_id == user))
            await cleanup.commit()
