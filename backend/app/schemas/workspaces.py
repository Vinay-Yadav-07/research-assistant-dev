"""Request and response schemas for the workspace endpoints (FR-02)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

# Must equal `app.models.workspace.KNOWLEDGE_MODES`; a unit test keeps them in sync.
KnowledgeMode = Literal["corpus_only", "corpus_web"]
WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
WorkspaceDescription = Annotated[str, StringConstraints(max_length=2000)]


class WorkspaceCreate(BaseModel):
    """Body of `POST /workspaces`."""

    model_config = ConfigDict(extra="forbid")

    name: WorkspaceName
    description: WorkspaceDescription | None = None
    default_mode: KnowledgeMode = "corpus_only"


class WorkspaceUpdate(BaseModel):
    """Body of `PATCH /workspaces/{id}`; only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: WorkspaceName | None = None
    # `null` clears the description.
    description: WorkspaceDescription | None = None
    default_mode: KnowledgeMode | None = None
    # `true` archives, `false` restores (reversible, unlike DELETE).
    archived: bool | None = None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> "WorkspaceUpdate":
        """Only `description` may be set to null."""
        for field in ("name", "default_mode", "archived"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        """The fields the client sent, with their new values."""
        return self.model_dump(include=self.model_fields_set)


class WorkspaceRead(BaseModel):
    """A workspace as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    default_mode: KnowledgeMode
    archived: bool
    # S7 keyword summary of the workspace's ready documents; None until generated (D-068).
    keywords: list[str] | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
