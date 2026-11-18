"""Discover endpoints: search free scholarly sources, import open-access papers (D-077).

Another user's workspace answers 404 (D-047).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    get_app_settings,
    get_current_user,
    get_paper_import_service,
    get_pdf_fetcher,
    get_providers,
)
from app.core.auth import CurrentUser
from app.core.config import Settings
from app.providers.factory import Providers
from app.providers.fetch import PdfFetcher
from app.schemas.documents import DocumentUploadResult
from app.schemas.errors import ErrorResponse
from app.schemas.papers import PaperImportRequest, PaperSearchResponse, SearchScope
from app.services.papers import PaperImportService, search_papers

router = APIRouter(
    tags=["papers"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)

User = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/papers/search", response_model=PaperSearchResponse, operation_id="searchPapers")
async def search(
    user: User,
    providers: Annotated[Providers, Depends(get_providers)],
    fetcher: Annotated[PdfFetcher, Depends(get_pdf_fetcher)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    q: Annotated[str, Query(min_length=2, max_length=300)],
    source: SearchScope = "all",
    importable_only: Annotated[
        bool, Query(description="Only open-access works with a PDF link")
    ] = False,
) -> PaperSearchResponse:
    """Search arXiv and/or OpenAlex; `pdf_status` says whether a PDF answered (`verified`),
    a PDF link is known but unchecked (`unverified`), or there is only a link (`none`).

    Results come from external APIs and are untrusted text.
    """
    return await search_papers(
        providers.scholarly_search,
        fetcher,
        q,
        scope=source,
        limit=settings.discover_max_results,
        pdf_check_seconds=settings.discover_pdf_check_seconds,
        importable_only=importable_only,
    )


@router.post(
    "/workspaces/{workspace_id}/import",
    response_model=DocumentUploadResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="importPaper",
    responses={
        status.HTTP_200_OK: {
            "model": DocumentUploadResult,
            "description": "The user already has this PDF; nothing is ingested again.",
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
)
async def import_paper(
    workspace_id: UUID,
    body: PaperImportRequest,
    response: Response,
    user: User,
    service: Annotated[PaperImportService, Depends(get_paper_import_service)],
) -> DocumentUploadResult:
    """Download the paper's open-access PDF and ingest it; 409 `compatibility_warning`
    asks for "Import anyway" (`override`), 422 `not_open_access` means link only."""
    result = await service.import_paper(
        user.id, workspace_id, body.source, body.external_id, override=body.override
    )
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return result
