"""Workspace management (FR-02). Missing and non-owned workspaces raise NotFoundError (D-047)."""

import logging
from typing import Protocol
from uuid import UUID

from app.core.errors import NotFoundError
from app.models.workspace import Workspace
from app.schemas.workspaces import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.services.documents import FileStorage, remove_stored_files

logger = logging.getLogger(__name__)


class WorkspaceStore(Protocol):
    """Persistence the service needs; `WorkspaceRepository` implements it."""

    async def list_owned(self, user_id: UUID, *, limit: int, offset: int) -> list[Workspace]: ...

    async def get(self, user_id: UUID, workspace_id: UUID) -> Workspace | None: ...

    async def create(
        self, user_id: UUID, *, name: str, description: str | None, default_mode: str
    ) -> Workspace: ...

    async def update(
        self, user_id: UUID, workspace_id: UUID, changes: dict[str, object]
    ) -> Workspace | None: ...

    async def delete(self, user_id: UUID, workspace_id: UUID) -> list[str] | None: ...

    async def commit(self) -> None: ...


class WorkspaceService:
    """Creates, lists, renames, archives, and deletes one user's workspaces."""

    def __init__(self, store: WorkspaceStore, storage: FileStorage | None = None) -> None:
        self._store = store
        self._storage = storage

    async def list_owned(self, user_id: UUID, *, limit: int, offset: int) -> list[WorkspaceRead]:
        """The user's workspaces, newest first."""
        workspaces = await self._store.list_owned(user_id, limit=limit, offset=offset)
        return [WorkspaceRead.model_validate(workspace) for workspace in workspaces]

    async def get(self, user_id: UUID, workspace_id: UUID) -> WorkspaceRead:
        """One owned workspace."""
        workspace = await self._store.get(user_id, workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        return WorkspaceRead.model_validate(workspace)

    async def create(self, user_id: UUID, data: WorkspaceCreate) -> WorkspaceRead:
        """Create a workspace owned by `user_id`."""
        workspace = await self._store.create(
            user_id, name=data.name, description=data.description, default_mode=data.default_mode
        )
        result = WorkspaceRead.model_validate(workspace)
        await self._store.commit()
        return result

    async def update(
        self, user_id: UUID, workspace_id: UUID, data: WorkspaceUpdate
    ) -> WorkspaceRead:
        """Rename, describe, change the default mode, archive, or restore."""
        workspace = await self._store.update(user_id, workspace_id, data.changes())
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        result = WorkspaceRead.model_validate(workspace)
        await self._store.commit()
        return result

    async def delete(self, user_id: UUID, workspace_id: UUID) -> None:
        """Permanently delete the workspace and its unshared documents (D-046)."""
        storage_paths = await self._store.delete(user_id, workspace_id)
        if storage_paths is None:
            raise NotFoundError("Workspace not found.")
        await self._store.commit()
        logger.info(
            "Deleted workspace %s with %d stored files to remove", workspace_id, len(storage_paths)
        )
        await remove_stored_files(self._storage, storage_paths)
