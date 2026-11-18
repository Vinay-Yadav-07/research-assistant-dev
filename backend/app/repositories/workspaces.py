"""Workspace persistence. Every query filters by the owning `user_id`."""

from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.document import Document
from app.models.workspace import Workspace, WorkspaceDocument


class WorkspaceRepository:
    """Reads and writes one user's workspaces within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_owned(self, user_id: UUID, *, limit: int, offset: int) -> list[Workspace]:
        """The user's workspaces, archived included, newest first."""
        result = await self._session.scalars(
            select(Workspace)
            .where(Workspace.user_id == user_id)
            .order_by(Workspace.created_at.desc(), Workspace.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def get(self, user_id: UUID, workspace_id: UUID) -> Workspace | None:
        """The workspace, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(Workspace).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )

    async def create(
        self, user_id: UUID, *, name: str, description: str | None, default_mode: str
    ) -> Workspace:
        """Insert a workspace and return it with its server-generated fields."""
        workspace = Workspace(
            user_id=user_id, name=name, description=description, default_mode=default_mode
        )
        self._session.add(workspace)
        await self._session.flush()
        await self._session.refresh(workspace)
        return workspace

    async def update(
        self, user_id: UUID, workspace_id: UUID, changes: dict[str, object]
    ) -> Workspace | None:
        """Apply `changes` to an owned workspace; None if it is missing or not owned."""
        workspace = await self.get(user_id, workspace_id)
        if workspace is None or not changes:
            return workspace
        for field, value in changes.items():
            setattr(workspace, field, value)
        await self._session.flush()
        await self._session.refresh(workspace)
        return workspace

    async def delete(self, user_id: UUID, workspace_id: UUID) -> list[str] | None:
        """Delete the workspace and every document no other workspace uses (D-046).

        Links and the topic profile cascade from the workspace, chunks from the documents.
        Returns the deleted documents' storage paths, or None if the workspace is missing or
        not owned.
        """
        owned = await self._session.scalar(
            select(Workspace.id)
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .with_for_update()
        )
        if owned is None:
            return None
        other_link = aliased(WorkspaceDocument)
        # FOR UPDATE blocks a concurrent link to another workspace until this commits.
        unshared = await self._session.execute(
            select(Document.id, Document.storage_path)
            .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
            .where(
                WorkspaceDocument.workspace_id == workspace_id,
                Document.user_id == user_id,
                ~exists().where(
                    other_link.document_id == Document.id,
                    other_link.workspace_id != workspace_id,
                ),
            )
            .with_for_update(of=Document)
        )
        rows = unshared.all()
        await self._session.execute(
            delete(Workspace).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )
        if rows:
            await self._session.execute(
                delete(Document).where(
                    Document.id.in_([row.id for row in rows]), Document.user_id == user_id
                )
            )
        return [row.storage_path for row in rows if row.storage_path is not None]

    async def commit(self) -> None:
        """Commit the session's transaction."""
        await self._session.commit()
