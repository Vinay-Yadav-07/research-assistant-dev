"""Workspace endpoints (FR-02). Another user's workspace answers 404, like a missing one (D-047)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import get_current_user, get_workspace_service
from app.core.auth import CurrentUser
from app.schemas.errors import ErrorResponse
from app.schemas.workspaces import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.services.workspaces import WorkspaceService

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

router = APIRouter(
    prefix="/workspaces",
    tags=["workspaces"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
NOT_FOUND: dict[int | str, dict[str, Any]] = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[WorkspaceService, Depends(get_workspace_service)]


@router.get("", response_model=list[WorkspaceRead], operation_id="listWorkspaces")
async def list_workspaces(
    user: User,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkspaceRead]:
    """The caller's workspaces, archived included, newest first."""
    return await service.list_owned(user.id, limit=limit, offset=offset)


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createWorkspace",
)
async def create_workspace(body: WorkspaceCreate, user: User, service: Service) -> WorkspaceRead:
    """Create a workspace owned by the caller."""
    return await service.create(user.id, body)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    operation_id="getWorkspace",
    responses=NOT_FOUND,
)
async def get_workspace(workspace_id: UUID, user: User, service: Service) -> WorkspaceRead:
    """One of the caller's workspaces."""
    return await service.get(user.id, workspace_id)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    operation_id="updateWorkspace",
    responses=NOT_FOUND,
)
async def update_workspace(
    workspace_id: UUID, body: WorkspaceUpdate, user: User, service: Service
) -> WorkspaceRead:
    """Rename, describe, or change the default mode; `archived` archives or restores."""
    return await service.update(user.id, workspace_id, body)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteWorkspace",
    responses=NOT_FOUND,
)
async def delete_workspace(workspace_id: UUID, user: User, service: Service) -> Response:
    """Permanently delete the workspace and every document no other workspace uses."""
    await service.delete(user.id, workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
