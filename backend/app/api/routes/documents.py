"""Document endpoints (FR-03, FR-22, SRS §16).

Another user's workspace or document answers 404 (D-047).
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.api.deps import (
    get_app_settings,
    get_compatibility_service,
    get_current_user,
    get_document_service,
)
from app.core.auth import CurrentUser
from app.core.config import Settings
from app.schemas.documents import (
    CompatibilityResult,
    DocumentFileUrl,
    DocumentRead,
    DocumentUploadResult,
)
from app.schemas.errors import ErrorResponse
from app.services.compatibility import CompatibilityService
from app.services.documents import DocumentService, read_upload

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

router = APIRouter(
    tags=["documents"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
STORAGE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[DocumentService, Depends(get_document_service)]
PdfFile = Annotated[UploadFile, File(description="A PDF of at most 25 MB")]


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentUploadResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="uploadDocument",
    responses={
        status.HTTP_200_OK: {
            "model": DocumentUploadResult,
            "description": "The user already has this file; nothing is ingested again.",
        },
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
        **STORAGE_ERRORS,
    },
)
async def upload_document(
    workspace_id: UUID,
    file: PdfFile,
    response: Response,
    user: User,
    service: Service,
    settings: Annotated[Settings, Depends(get_app_settings)],
    override: Annotated[
        bool, Form(description='True when the user chose "Import anyway" after a warning')
    ] = False,
) -> DocumentUploadResult:
    """Upload a PDF; 202 starts ingestion, 200 returns the user's existing copy.

    Call the compatibility check first; the upload itself does not refuse unrelated documents.
    """
    data = await read_upload(file.read, max_bytes=settings.max_upload_bytes)
    result = await service.upload(user.id, workspace_id, data, override=override)
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return result


@router.post(
    "/workspaces/{workspace_id}/documents/compatibility",
    response_model=CompatibilityResult,
    operation_id="checkDocumentCompatibility",
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
    },
)
async def check_compatibility(
    workspace_id: UUID,
    file: PdfFile,
    user: User,
    service: Annotated[CompatibilityService, Depends(get_compatibility_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CompatibilityResult:
    """Score a PDF against the workspace topic before uploading it (FR-22); nothing is stored."""
    data = await read_upload(file.read, max_bytes=settings.max_upload_bytes)
    return await service.check(user.id, workspace_id, data)


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=list[DocumentRead],
    operation_id="listWorkspaceDocuments",
)
async def list_documents(
    workspace_id: UUID,
    user: User,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentRead]:
    """Documents in the workspace with their ingestion status, most recently added first."""
    return await service.list_in_workspace(user.id, workspace_id, limit=limit, offset=offset)


@router.put(
    "/workspaces/{workspace_id}/documents/{document_id}",
    response_model=DocumentRead,
    operation_id="linkDocument",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def link_document(
    workspace_id: UUID,
    document_id: UUID,
    user: User,
    service: Service,
    override: Annotated[
        bool, Query(description='True when the user chose "Import anyway" after a warning')
    ] = False,
) -> DocumentRead:
    """Add one of the caller's existing documents to the workspace (idempotent).

    409 `compatibility_warning` (details: score, threshold) if the document looks unrelated;
    repeat with `override=true` to link it anyway.
    """
    return await service.link(user.id, workspace_id, document_id, override=override)


@router.delete(
    "/workspaces/{workspace_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="removeDocument",
)
async def remove_document(
    workspace_id: UUID, document_id: UUID, user: User, service: Service
) -> Response:
    """Remove the document from the workspace; delete it if no other workspace uses it."""
    await service.remove(user.id, workspace_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}", response_model=DocumentRead, operation_id="getDocument")
async def get_document(document_id: UUID, user: User, service: Service) -> DocumentRead:
    """One of the caller's documents, including its ingestion status."""
    return await service.get(user.id, document_id)


@router.get(
    "/documents/{document_id}/file",
    response_model=DocumentFileUrl,
    operation_id="getDocumentFileUrl",
    responses=STORAGE_ERRORS,
)
async def get_document_file(document_id: UUID, user: User, service: Service) -> DocumentFileUrl:
    """A short-lived signed URL for the stored PDF."""
    return await service.file_url(user.id, document_id)
