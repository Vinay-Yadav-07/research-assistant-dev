"""Error response envelope shared by every endpoint."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """Machine-readable code, human-readable message, and optional details."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Envelope returned for every error: `{"error": {...}}`."""

    error: ErrorBody
