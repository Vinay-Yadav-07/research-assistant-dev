"""Chat endpoints: history (FR-25), claim evidence (FR-12, FR-13), and QA runs (SRS §16.1, §16.2).

Another user's workspace, conversation, message, or run answers 404 (D-047). Asking a question
and resuming a paused run stream the run's events over SSE; the run starts in a dependency, so a
rejected request gets a normal error response before the stream opens. A client that stops
listening does not stop the run: its answer is still saved to the conversation.
"""

from collections.abc import AsyncIterable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.sse import EventSourceResponse

from app.api.deps import (
    get_conversation_service,
    get_current_user,
    get_qa_runner,
    resume_qa_run,
    start_qa_run,
)
from app.core.auth import CurrentUser
from app.graphs.qa_runner import QAEvent, QARun, QARunner, RunRead
from app.schemas.conversations import (
    ClaimRead,
    ConversationCreate,
    ConversationRead,
    HistoryMessageRead,
)
from app.schemas.errors import ErrorResponse
from app.services.conversations import ConversationService

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

router = APIRouter(
    tags=["conversations"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)

# The streaming endpoints reject a request with JSON before the stream opens; without explicit
# content, OpenAPI would list these errors under `text/event-stream`.
_JSON_ERROR = {
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
}
STREAM_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {**_JSON_ERROR, "description": description}
    for code, description in (
        (status.HTTP_401_UNAUTHORIZED, "Missing or invalid token"),
        (status.HTTP_404_NOT_FOUND, "Not found"),
        (status.HTTP_409_CONFLICT, "The run is not waiting for approval"),
        (status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid input"),
        (status.HTTP_503_SERVICE_UNAVAILABLE, "The database is not configured"),
    )
}
ASK_ERRORS = {code: r for code, r in STREAM_ERRORS.items() if code != status.HTTP_409_CONFLICT}

User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[ConversationService, Depends(get_conversation_service)]
Runner = Annotated[QARunner, Depends(get_qa_runner)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/workspaces/{workspace_id}/conversations",
    response_model=list[ConversationRead],
    operation_id="listConversations",
)
async def list_conversations(
    workspace_id: UUID,
    user: User,
    service: Service,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> list[ConversationRead]:
    """The workspace's conversations, most recently active first."""
    return await service.list_in_workspace(user.id, workspace_id, limit=limit, offset=offset)


@router.post(
    "/workspaces/{workspace_id}/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createConversation",
)
async def create_conversation(
    workspace_id: UUID, body: ConversationCreate, user: User, service: Service
) -> ConversationRead:
    """Start a conversation; its mode defaults to the workspace's `default_mode`."""
    return await service.create(user.id, workspace_id, body)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[HistoryMessageRead],
    operation_id="listMessages",
)
async def list_messages(
    conversation_id: UUID,
    user: User,
    service: Service,
    limit: Limit = DEFAULT_PAGE_SIZE,
    offset: Offset = 0,
) -> list[HistoryMessageRead]:
    """The conversation's messages, oldest first, each answer with its claims and citations.

    A question with no answer after it is still running, paused, or failed: its `run_id`
    leads to `getRun`."""
    return await service.list_messages(user.id, conversation_id, limit=limit, offset=offset)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=EventSourceResponse,
    operation_id="sendMessage",
    responses=ASK_ERRORS,
)
async def send_message(run: Annotated[QARun, Depends(start_qa_run)]) -> AsyncIterable[QAEvent]:
    """Ask a question; streams `status` events, then `claims`, `citations`, and `done`, or
    `approval_required` when the corpus is insufficient, or `error`."""
    async for event in run.events():
        yield event


@router.post(
    "/runs/{run_id}/resume",
    response_class=EventSourceResponse,
    operation_id="resumeRun",
    responses=STREAM_ERRORS,
)
async def resume_run(run: Annotated[QARun, Depends(resume_qa_run)]) -> AsyncIterable[QAEvent]:
    """Answer a paused run's approval request; streams the rest of the run like `sendMessage`."""
    async for event in run.events():
        yield event


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
    operation_id="getRun",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}},
)
async def get_run(run_id: UUID, user: User, runner: Runner) -> RunRead:
    """The run's status; a paused run includes the approval request to show again."""
    return await runner.get_run(user.id, run_id)


@router.get(
    "/messages/{message_id}/claims",
    response_model=list[ClaimRead],
    operation_id="listMessageClaims",
)
async def list_message_claims(message_id: UUID, user: User, service: Service) -> list[ClaimRead]:
    """The answer's claims in order, each with its status, evidence, and citations."""
    return await service.list_claims(user.id, message_id)
