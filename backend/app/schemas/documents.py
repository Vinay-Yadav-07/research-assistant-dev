"""Response schemas for the document endpoints (FR-03, SRS §16)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Must equal `app.models.document.DOCUMENT_STATUSES`; a unit test keeps them in sync.
DocumentStatus = Literal["uploaded", "parsing", "embedding", "ready", "failed"]
DocumentSource = Literal["upload", "import"]


class DocumentRead(BaseModel):
    """A document as returned by the API. `error` explains a `failed` status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    authors: list[str] = Field(default_factory=list)
    year: int | None
    venue: str | None
    doi: str | None
    source: DocumentSource
    source_url: str | None
    page_count: int | None
    status: DocumentStatus
    error: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("authors", mode="before")
    @classmethod
    def _null_authors_are_empty(cls, value: object) -> object:
        return [] if value is None else value


class DocumentUploadResult(BaseModel):
    """Result of `POST /workspaces/{id}/documents`.

    `duplicate` is true when the user already had this file; nothing is ingested again. If
    `linked` is then false, the client may offer to link the existing document with
    `PUT /workspaces/{id}/documents/{document_id}`.
    """

    document: DocumentRead
    duplicate: bool
    linked: bool


class DocumentFileUrl(BaseModel):
    """A short-lived signed URL for downloading the stored PDF (NFR-09)."""

    url: str
    expires_at: datetime


class CompatibilityResult(BaseModel):
    """Result of `POST /workspaces/{id}/documents/compatibility` (FR-22, SRS §11.2).

    `score` is the cosine similarity between the document and the workspace topic profile.
    `skipped` is true for a workspace without ready documents; `score` is then null and the
    document counts as compatible. When `compatible` is false, the client offers
    [Import anyway] (upload with `override=true`), [Move to another workspace], or [Cancel].
    """

    score: float | None
    threshold: float
    compatible: bool
    skipped: bool
