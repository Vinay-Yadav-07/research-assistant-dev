"""Request and response schemas for the research endpoints (SRS §16.1)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

FindingType = Literal["answer", "comparison", "contradiction", "gap", "review"]


class CompareRequest(BaseModel):
    """Body of `POST /workspaces/{id}/compare`; the upper limit is COMPARE_MAX_PAPERS."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] = Field(min_length=2)

    @field_validator("document_ids")
    @classmethod
    def _unique(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("document_ids must be unique")
        return value


class SynthesizeRequest(CompareRequest):
    """Body of `POST /workspaces/{id}/synthesize`: a topic and the papers to synthesize."""

    topic: str = Field(min_length=1, max_length=500)


class ContradictionsRequest(SynthesizeRequest):
    """Body of `POST /workspaces/{id}/contradictions`: a topic and the papers to check."""


class GapsRequest(CompareRequest):
    """Body of `POST /workspaces/{id}/gaps`: the papers to analyse for corpus gaps."""


class FindingCreate(BaseModel):
    """Body of `POST /workspaces/{id}/findings`: an output to keep (FR-26).

    `content` is the output as the API returned it (e.g. a `ComparisonTable`); its `text` and
    `citations` fields are what the Markdown and BibTeX exports read.
    """

    model_config = ConfigDict(extra="forbid")

    type: FindingType
    title: str = Field(min_length=1, max_length=300)
    content: dict[str, Any]


class FindingRead(BaseModel):
    """A saved finding as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    type: FindingType
    title: str
    content: dict[str, Any] = Field(validation_alias="content_json")
    created_at: datetime
