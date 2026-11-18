"""Retrieval debug endpoint (SRS §22 Phase 1): every S2 stage for one query, owner only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user, get_retrieval_service
from app.core.auth import CurrentUser
from app.schemas.errors import ErrorResponse
from app.schemas.retrieval import RetrievalDebugRequest
from app.services.retrieval import RetrievalDebug, RetrievalService

router = APIRouter(
    tags=["retrieval"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)


@router.post(
    "/workspaces/{workspace_id}/retrieval/debug",
    response_model=RetrievalDebug,
    operation_id="debugRetrieval",
)
async def debug_retrieval(
    workspace_id: UUID,
    body: RetrievalDebugRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> RetrievalDebug:
    """Dense, full-text, fused, and reranked candidates for `query`, with timings."""
    return await service.debug(user.id, workspace_id, body.query, top_k=body.top_k)
