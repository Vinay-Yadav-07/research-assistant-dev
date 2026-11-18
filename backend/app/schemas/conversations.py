"""Request and response schemas for chat history (FR-25) and claim evidence (FR-12, FR-13)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.workspaces import KnowledgeMode

# Must equal the tuples in `app.models.conversation`; a unit test keeps them in sync.
MessageMode = Literal["corpus_only", "corpus_web", "general_knowledge"]
MessageRole = Literal["user", "assistant"]
ClaimStatus = Literal["supported", "partially_supported", "unsupported", "uncertain"]
CitationSourceType = Literal["workspace", "external", "general"]
# Must equal `app.models.agent_run.RUN_STATUSES`; a unit test keeps them in sync.
RunStatus = Literal["running", "interrupted", "completed", "failed"]
ConversationTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class ConversationCreate(BaseModel):
    """Body of `POST /workspaces/{id}/conversations`."""

    model_config = ConfigDict(extra="forbid")

    title: ConversationTitle | None = None
    # Defaults to the workspace's `default_mode`; corpus_web is logged as an approval.
    mode: KnowledgeMode | None = None


class MessageCreate(BaseModel):
    """Body of `POST /conversations/{id}/messages`; the S6 input check runs on `content`."""

    model_config = ConfigDict(extra="forbid")

    content: str


class RunResume(BaseModel):
    """Body of `POST /runs/{id}/resume`: one of the options the approval request offered."""

    model_config = ConfigDict(extra="forbid")

    decision: MessageMode


class ConversationRead(BaseModel):
    """A conversation as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    title: str | None
    mode: KnowledgeMode
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    """A message as returned by the API; a question's `run_id` is the run that answers it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    mode: MessageMode
    run_id: UUID | None
    created_at: datetime


class EvidenceRead(BaseModel):
    """A chunk judged against a claim; `chunk_id` is null once its document is deleted."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chunk_id: UUID | None
    score: float | None


class CitationRead(BaseModel):
    """A cited source: live links (null once deleted) and the snapshot saved with the answer."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: CitationSourceType
    document_id: UUID | None
    chunk_id: UUID | None
    document_title: str | None
    page_start: int | None
    page_end: int | None
    section: str | None
    quote: str | None


class ClaimRead(BaseModel):
    """A verified claim with its evidence and citations."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    text: str
    status: ClaimStatus
    support_score: float | None
    evidence: list[EvidenceRead]
    citations: list[CitationRead]


class HistoryMessageRead(MessageRead):
    """A message in the conversation history with its claims (none for a question or an
    abstention), so the history loads in one request."""

    claims: list[ClaimRead]
