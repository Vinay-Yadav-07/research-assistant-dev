"""Document, link, and chunk persistence. Every query on user data filters by `user_id`."""

from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.topic_profiles import TopicProfileRepository
from app.schemas.documents import DocumentSource

IN_PROGRESS_STATUSES = ("uploaded", "parsing", "embedding")


@dataclass(frozen=True)
class NewChunk:
    """A chunk row ready to insert."""

    chunk_index: int
    page_start: int
    page_end: int
    section: str | None
    text: str
    token_count: int
    content_hash: str
    embedding: list[float]
    embedding_model: str


@dataclass(frozen=True)
class DocumentFields:
    """Metadata ingestion writes onto the document record."""

    title: str | None
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    page_count: int


class DocumentRepository:
    """Reads and writes one user's documents within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._profiles = TopicProfileRepository(session)

    @property
    def profiles(self) -> TopicProfileRepository:
        """Topic profiles on the same session, for updates in the same transaction."""
        return self._profiles

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        """True if the workspace exists and belongs to `user_id`."""
        found = await self._session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        return found is not None

    async def get(self, user_id: UUID, document_id: UUID) -> Document | None:
        """The document, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )

    async def find_by_hash(self, user_id: UUID, content_hash: str) -> Document | None:
        """The user's document with these file bytes, if any."""
        return await self._session.scalar(
            select(Document).where(
                Document.user_id == user_id, Document.content_hash == content_hash
            )
        )

    async def create(
        self,
        user_id: UUID,
        document_id: UUID,
        *,
        content_hash: str,
        storage_path: str,
        source: DocumentSource = "upload",
        source_url: str | None = None,
    ) -> Document | None:
        """Insert an `uploaded` document; None if the user already has this file.

        A concurrent insert of the same file waits for the other transaction and then
        returns None (unique `(user_id, content_hash)`, D-057).
        """
        inserted = await self._session.scalar(
            pg_insert(Document)
            .values(
                id=document_id,
                user_id=user_id,
                content_hash=content_hash,
                storage_path=storage_path,
                source=source,
                source_url=source_url,
                status="uploaded",
            )
            .on_conflict_do_nothing(index_elements=["user_id", "content_hash"])
            .returning(Document.id)
        )
        if inserted is None:
            return None
        return await self.get(user_id, document_id)

    async def is_linked(self, user_id: UUID, workspace_id: UUID, document_id: UUID) -> bool:
        """True if the user's document is linked to the user's workspace."""
        found = await self._session.scalar(
            select(WorkspaceDocument.document_id)
            .join(Document, Document.id == WorkspaceDocument.document_id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                WorkspaceDocument.document_id == document_id,
                Document.user_id == user_id,
                Workspace.user_id == user_id,
            )
        )
        return found is not None

    async def link(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        compatibility_score: float | None = None,
        override: bool = False,
    ) -> None:
        """Link a document to a workspace with its compatibility result; a no-op if linked.

        The caller has checked that the user owns both.
        """
        await self._session.execute(
            pg_insert(WorkspaceDocument)
            .values(
                workspace_id=workspace_id,
                document_id=document_id,
                compatibility_score=compatibility_score,
                override=override,
            )
            .on_conflict_do_nothing()
        )

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Document]:
        """The user's documents linked to the workspace, most recently added first."""
        result = await self._session.scalars(
            select(Document)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                Workspace.user_id == user_id,
                Document.user_id == user_id,
            )
            .order_by(WorkspaceDocument.added_at.desc(), Document.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def unlink(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID
    ) -> tuple[bool, str | None]:
        """Remove the document from the workspace; delete it if no other workspace uses it.

        Returns (found, storage path of a deleted document). `found` is False if the document
        is not linked to the workspace or either is not owned by `user_id`.
        """
        # FOR UPDATE blocks a concurrent link to another workspace until this commits (D-046).
        locked = await self._session.scalar(
            select(Document.id)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                WorkspaceDocument.workspace_id == workspace_id,
                Workspace.user_id == user_id,
            )
            .with_for_update(of=Document)
        )
        if locked is None:
            return False, None
        await self._session.execute(
            delete(WorkspaceDocument).where(
                WorkspaceDocument.workspace_id == workspace_id,
                WorkspaceDocument.document_id == document_id,
            )
        )
        other_link = aliased(WorkspaceDocument)
        storage_path = await self._session.scalar(
            delete(Document)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                ~exists().where(other_link.document_id == Document.id),
            )
            .returning(Document.storage_path)
        )
        return True, storage_path

    async def restart(self, user_id: UUID, document_id: UUID) -> Document | None:
        """Put a `failed` document back to `uploaded`; None if it is not failed (any more)."""
        return await self._session.scalar(
            update(Document)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                Document.status == "failed",
            )
            .values(status="uploaded", error=None)
            .returning(Document)
            .execution_options(populate_existing=True)
        )

    async def set_status(
        self, user_id: UUID, document_id: UUID, status: str, *, error: str | None = None
    ) -> bool:
        """Move the document to `status`; False if it no longer exists."""
        updated = await self._session.scalar(
            update(Document)
            .where(Document.id == document_id, Document.user_id == user_id)
            .values(status=status, error=error)
            .returning(Document.id)
        )
        return updated is not None

    async def lock(self, user_id: UUID, document_id: UUID) -> bool:
        """Lock the document row until commit; False if it no longer exists."""
        locked = await self._session.scalar(
            select(Document.id)
            .where(Document.id == document_id, Document.user_id == user_id)
            .with_for_update()
        )
        return locked is not None

    async def complete(
        self,
        user_id: UUID,
        document_id: UUID,
        fields: DocumentFields,
        chunks: Sequence[NewChunk],
    ) -> None:
        """Store metadata and chunks and mark the document `ready`. Call `lock` first."""
        await self._session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        if chunks:
            await self._session.execute(
                insert(Chunk),
                [
                    {
                        "document_id": document_id,
                        "chunk_index": chunk.chunk_index,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "section": chunk.section,
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                        "content_hash": chunk.content_hash,
                        "embedding": chunk.embedding,
                        "embedding_model": chunk.embedding_model,
                    }
                    for chunk in chunks
                ],
            )
        await self._session.execute(
            update(Document)
            .where(Document.id == document_id, Document.user_id == user_id)
            .values(
                title=fields.title,
                authors=fields.authors or None,
                year=fields.year,
                venue=fields.venue,
                doi=fields.doi,
                page_count=fields.page_count,
                status="ready",
                error=None,
            )
        )

    async def fail_stale(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int:
        """Mark in-progress documents not updated within `older_than` as failed (D-049).

        `exclude` holds documents the caller is still processing. A system-wide sweep, so it
        is not scoped to one user. Returns the count.
        """
        conditions = [
            Document.status.in_(IN_PROGRESS_STATUSES),
            Document.updated_at < func.now() - older_than,
        ]
        if exclude:
            conditions.append(Document.id.not_in(list(exclude)))
        result = await self._session.execute(
            update(Document)
            .where(*conditions)
            .values(status="failed", error=reason)
            .returning(Document.id)
        )
        return len(result.all())

    async def commit(self) -> None:
        """Commit the session's transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the session's transaction."""
        await self._session.rollback()


def document_store_factory(
    sessions: async_sessionmaker[AsyncSession],
) -> Callable[[], AbstractAsyncContextManager[DocumentRepository]]:
    """Open a repository on a fresh session for each unit of background work."""

    @asynccontextmanager
    async def open_store() -> AsyncIterator[DocumentRepository]:
        async with sessions() as session:
            yield DocumentRepository(session)

    return open_store
