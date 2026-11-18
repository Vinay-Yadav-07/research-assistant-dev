"""Topic profile persistence for S7 (SRS §11.2). Every query on user data filters by `user_id`."""

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models._types import EMBEDDING_DIMENSION
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.topic_profile import TopicProfile
from app.models.workspace import Workspace, WorkspaceDocument


@dataclass(frozen=True)
class ProfileState:
    """A workspace centroid (None while empty) and the documents averaged into it."""

    centroid: list[float] | None
    document_count: int


@dataclass(frozen=True)
class SummaryDocument:
    """A ready document's title and first chunk, the input to the S7 keyword summary."""

    title: str | None
    text: str


class TopicProfileRepository:
    """Reads and writes topic profiles and link scores within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None:
        """The workspace's profile (empty if never set); None if the workspace is not owned."""
        row = (
            await self._session.execute(
                select(Workspace.id, TopicProfile.centroid_embedding, TopicProfile.document_count)
                .outerjoin(TopicProfile, TopicProfile.workspace_id == Workspace.id)
                .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return _state(row.centroid_embedding, row.document_count)

    async def lock(self, user_id: UUID, workspace_id: UUID) -> ProfileState | None:
        """Create the profile if missing and lock it until commit; None if not owned."""
        owned = await self._session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        if owned is None:
            return None
        await self._session.execute(
            pg_insert(TopicProfile)
            .values(workspace_id=workspace_id, document_count=0)
            .on_conflict_do_nothing()
        )
        row = (
            await self._session.execute(
                select(TopicProfile.centroid_embedding, TopicProfile.document_count)
                .where(TopicProfile.workspace_id == workspace_id)
                .with_for_update()
            )
        ).one()
        return _state(row.centroid_embedding, row.document_count)

    async def save(self, workspace_id: UUID, state: ProfileState) -> None:
        """Write a profile the caller has locked."""
        await self._session.execute(
            update(TopicProfile)
            .where(TopicProfile.workspace_id == workspace_id)
            .values(centroid_embedding=state.centroid, document_count=state.document_count)
        )

    async def document_vector(
        self, user_id: UUID, document_id: UUID, *, first_chunks: int
    ) -> list[float] | None:
        """Mean embedding of the user's document's first chunks; None if it has none."""
        first = (
            select(Chunk.embedding)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.document_id == document_id, Document.user_id == user_id)
            .order_by(Chunk.chunk_index)
            .limit(first_chunks)
            .subquery()
        )
        mean = await self._session.scalar(
            select(func.avg(first.c.embedding, type_=Vector(EMBEDDING_DIMENSION)))
        )
        return None if mean is None else [float(value) for value in mean]

    async def linked_workspaces(self, user_id: UUID, document_id: UUID) -> list[UUID]:
        """The user's workspaces the user's document is linked to."""
        result = await self._session.scalars(
            select(WorkspaceDocument.workspace_id)
            .join(Workspace, Workspace.id == WorkspaceDocument.workspace_id)
            .join(Document, Document.id == WorkspaceDocument.document_id)
            .where(
                WorkspaceDocument.document_id == document_id,
                Workspace.user_id == user_id,
                Document.user_id == user_id,
            )
            .order_by(WorkspaceDocument.workspace_id)
        )
        return list(result)

    async def set_score(self, workspace_id: UUID, document_id: UUID, score: float | None) -> None:
        """Record the link's compatibility score; the caller has checked ownership."""
        await self._session.execute(
            update(WorkspaceDocument)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                WorkspaceDocument.document_id == document_id,
            )
            .values(compatibility_score=score)
        )

    async def summary_documents(
        self, user_id: UUID, workspace_id: UUID, *, limit: int
    ) -> list[SummaryDocument] | None:
        """Title and first chunk of the workspace's ready documents, most recently added first;
        None if the workspace is not owned."""
        owned = await self._session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        if owned is None:
            return None
        rows = await self._session.execute(
            select(Document.title, Chunk.text)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .join(Chunk, and_(Chunk.document_id == Document.id, Chunk.chunk_index == 0))
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                Document.user_id == user_id,
                Document.status == "ready",
            )
            .order_by(WorkspaceDocument.added_at.desc(), Document.id)
            .limit(limit)
        )
        return [SummaryDocument(title=row.title, text=row.text) for row in rows]

    async def save_summary(
        self, user_id: UUID, workspace_id: UUID, *, keywords: list[str] | None, summary: str | None
    ) -> None:
        """Store the keyword summary on the user's workspace profile (if it has one)."""
        await self._session.execute(
            update(TopicProfile)
            .where(
                TopicProfile.workspace_id == workspace_id,
                TopicProfile.workspace_id.in_(
                    select(Workspace.id).where(Workspace.user_id == user_id)
                ),
            )
            .values(keywords=keywords, summary=summary)
        )

    async def commit(self) -> None:
        """Commit the session (only for stores opened by `topic_profile_store_factory`)."""
        await self._session.commit()


def topic_profile_store_factory(
    sessions: async_sessionmaker[AsyncSession],
) -> Callable[[], AbstractAsyncContextManager[TopicProfileRepository]]:
    """Open a repository on a fresh session for each unit of background work."""

    @asynccontextmanager
    async def open_store() -> AsyncIterator[TopicProfileRepository]:
        async with sessions() as session:
            yield TopicProfileRepository(session)

    return open_store


def _state(centroid: Iterable[float] | None, document_count: int | None) -> ProfileState:
    vector = None if centroid is None else [float(value) for value in centroid]
    return ProfileState(centroid=vector, document_count=document_count or 0)
