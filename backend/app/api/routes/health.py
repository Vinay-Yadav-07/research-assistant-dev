"""Liveness and readiness endpoints (no authentication)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_app_settings, get_readiness_service
from app.core.config import Settings
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.health import ReadinessService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, operation_id="getHealth")
async def get_health(settings: Annotated[Settings, Depends(get_app_settings)]) -> HealthResponse:
    """Liveness: returns 200 while the process is running. Touches no dependencies."""
    return HealthResponse(version=settings.app_version)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    operation_id="getReadiness",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def get_readiness(
    response: Response,
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadinessResponse:
    """Readiness: 200 when the database is reachable, otherwise 503."""
    result = await service.check()
    if result.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
