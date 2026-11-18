"""Response schemas for the health endpoints."""

from typing import Literal

from pydantic import BaseModel

DatabaseStatus = Literal["ok", "unavailable", "not_configured"]


class HealthResponse(BaseModel):
    """Liveness: the process is up."""

    status: Literal["ok"] = "ok"
    version: str


class ReadinessChecks(BaseModel):
    """Result of each dependency check."""

    database: DatabaseStatus


class ReadinessResponse(BaseModel):
    """Readiness: the service can reach its dependencies."""

    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks
