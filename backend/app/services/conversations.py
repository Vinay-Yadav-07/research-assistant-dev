"""Chat history (FR-25): conversations, messages, saved answers, and their run records.

Missing and non-owned workspaces, conversations, messages, and runs raise NotFoundError (D-047).
"""

from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.models.agent_run import AgentRun
from app.models.conversation import Approval, Citation, Claim, Conversation, Evidence, Message
from app.models.workspace import Workspace
from app.schemas.conversations import (
    CitationSourceType,
    ClaimRead,
    ClaimStatus,
    ConversationCreate,
    ConversationRead,
    HistoryMessageRead,
    MessageMode,
    MessageRead,
    RunStatus,
)
from app.schemas.workspaces import KnowledgeMode

CORPUS_WEB_REASON = "The conversation was started in Corpus + Web mode."


class ConversationStore(Protocol):
    """Persistence the service needs; `ConversationRepository` implements it."""

    async def get_workspace(self, user_id: UUID, workspace_id: UUID) -> Workspace | None: ...

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]: ...

    async def create(
        self, user_id: UUID, workspace_id: UUID, *, title: str | None, mode: str
    ) -> Conversation: ...

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None: ...

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[Message]: ...

    async def get_message(self, user_id: UUID, message_id: UUID) -> Message | None: ...

    async def list_claims(self, user_id: UUID, message_id: UUID) -> list[Claim]: ...

    async def add_approval(
        self,
        user_id: UUID,
        conversation_id: UUID,
        *,
        reason: str,
        options: list[str],
        decision: str,
        run_id: UUID | None = None,
    ) -> Approval: ...

    async def add_pending_approval(
        self,
        user_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        *,
        reason: str,
        options: list[str],
    ) -> Approval: ...

    async def get_pending_approval(self, user_id: UUID, run_id: UUID) -> Approval | None: ...

    async def decide_approval(self, user_id: UUID, approval_id: UUID, decision: str) -> bool: ...

    async def get_run(self, user_id: UUID, run_id: UUID) -> AgentRun | None: ...

    async def transition_run(
        self, user_id: UUID, run_id: UUID, *, from_status: str, changes: dict[str, object]
    ) -> bool: ...

    async def finish_run(self, user_id: UUID, run_id: UUID, changes: dict[str, object]) -> bool: ...

    async def fail_stale_runs(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int: ...

    async def create_run(
        self, user_id: UUID, workspace_id: UUID, conversation_id: UUID | None, *, workflow: str
    ) -> AgentRun: ...

    async def add_message(self, user_id: UUID, message: Message) -> Message | None: ...

    async def save_answer(
        self, user_id: UUID, message: Message, run_id: UUID, run_changes: dict[str, object]
    ) -> Message | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class EvidenceDraft(BaseModel):
    """A chunk the verifier judged against a claim."""

    chunk_id: UUID
    score: float | None = None


class CitationDraft(BaseModel):
    """A cited source plus the snapshot that keeps it readable after the source is deleted."""

    source_type: CitationSourceType
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    document_title: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section: str | None = None
    quote: str | None = None


class ClaimDraft(BaseModel):
    """A verified claim of a finished answer."""

    text: str
    status: ClaimStatus
    support_score: float | None = None
    evidence: list[EvidenceDraft] = []
    citations: list[CitationDraft] = []


class AnswerDraft(BaseModel):
    """A finished assistant answer with its claims, in answer order."""

    content: str
    mode: MessageMode
    claims: list[ClaimDraft] = []


class RunSummary(BaseModel):
    """How a run ended, stored on `agent_runs` (FR-28)."""

    # One of `app.models.agent_run.RUN_STATUSES` that ends a run.
    status: Literal["completed", "failed"] = "completed"
    latency_ms: int | None = None
    llm_calls: int = 0
    tokens: int = 0
    trace_url: str | None = None
    error: str | None = None


class RunProgress(BaseModel):
    """Cost of a run so far; a run paused for approval resumes from these totals."""

    latency_ms: int = 0
    llm_calls: int = 0
    tokens: int = 0


class StartedRun(BaseModel):
    """A run created for a user question, with what the graph needs to start."""

    run_id: UUID
    conversation_id: UUID
    workspace_id: UUID
    conversation_mode: KnowledgeMode
    question: MessageRead


class ResumedRun(BaseModel):
    """A paused run the user has decided on, back in the `running` state."""

    run_id: UUID
    conversation_id: UUID
    workspace_id: UUID
    decision: MessageMode
    progress: RunProgress


class PendingApproval(BaseModel):
    """The logged approval request a paused run waits on."""

    reason: str
    options: list[MessageMode]


class RunInfo(BaseModel):
    """A run's stored state."""

    id: UUID
    conversation_id: UUID | None
    status: RunStatus
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    pending_approval: PendingApproval | None


class ConversationService:
    """Creates and lists one user's conversations, and stores their messages and answers."""

    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[ConversationRead]:
        """The workspace's conversations, most recently active first."""
        await self._owned_workspace(user_id, workspace_id)
        conversations = await self._store.list_in_workspace(
            user_id, workspace_id, limit=limit, offset=offset
        )
        return [ConversationRead.model_validate(c) for c in conversations]

    async def create(
        self, user_id: UUID, workspace_id: UUID, data: ConversationCreate
    ) -> ConversationRead:
        """Start a conversation; corpus_web is logged as an approval for it (SRS §2.3)."""
        workspace = await self._owned_workspace(user_id, workspace_id)
        mode = data.mode or workspace.default_mode
        conversation = await self._store.create(user_id, workspace_id, title=data.title, mode=mode)
        if mode == "corpus_web":
            await self._store.add_approval(
                user_id,
                conversation.id,
                reason=CORPUS_WEB_REASON,
                options=["corpus_only", "corpus_web"],
                decision="corpus_web",
            )
        result = ConversationRead.model_validate(conversation)
        await self._store.commit()
        return result

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[HistoryMessageRead]:
        """The conversation's messages, oldest first, each answer with its claims."""
        await self._owned_conversation(user_id, conversation_id)
        messages = await self._store.list_messages(
            user_id, conversation_id, limit=limit, offset=offset
        )
        return [HistoryMessageRead.model_validate(m) for m in messages]

    async def list_claims(self, user_id: UUID, message_id: UUID) -> list[ClaimRead]:
        """The message's claims with their evidence and citations."""
        if await self._store.get_message(user_id, message_id) is None:
            raise NotFoundError("Message not found.")
        claims = await self._store.list_claims(user_id, message_id)
        return [ClaimRead.model_validate(c) for c in claims]

    async def add_user_message(
        self, user_id: UUID, conversation_id: UUID, *, content: str, mode: MessageMode
    ) -> MessageRead:
        """Store the user's question."""
        message = await self._store.add_message(
            user_id,
            Message(conversation_id=conversation_id, role="user", content=content, mode=mode),
        )
        if message is None:
            raise NotFoundError("Conversation not found.")
        result = MessageRead.model_validate(message)
        await self._store.commit()
        return result

    async def start_run(self, user_id: UUID, conversation_id: UUID, *, workflow: str) -> UUID:
        """Record a new run of `workflow` for the conversation and return its id."""
        conversation = await self._owned_conversation(user_id, conversation_id)
        run = await self._store.create_run(
            user_id, conversation.workspace_id, conversation.id, workflow=workflow
        )
        await self._store.commit()
        return run.id

    async def begin_run(
        self, user_id: UUID, conversation_id: UUID, *, question: str, workflow: str
    ) -> StartedRun:
        """Record a `running` run and store the user's question linked to it, together.

        The link lets the history find the run of a question that is still unanswered, such as
        one paused for approval (SRS §20).
        """
        conversation = await self._owned_conversation(user_id, conversation_id)
        try:
            run = await self._store.create_run(
                user_id, conversation.workspace_id, conversation.id, workflow=workflow
            )
            message = await self._store.add_message(
                user_id,
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content=question,
                    mode=conversation.mode,
                    run_id=run.id,
                ),
            )
            if message is None:
                raise NotFoundError("Conversation not found.")
            result = StartedRun(
                run_id=run.id,
                conversation_id=conversation.id,
                workspace_id=conversation.workspace_id,
                conversation_mode=cast(KnowledgeMode, conversation.mode),
                question=MessageRead.model_validate(message),
            )
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise
        return result

    async def pause_run(
        self,
        user_id: UUID,
        run_id: UUID,
        conversation_id: UUID,
        *,
        reason: str,
        options: list[str],
        progress: RunProgress,
    ) -> None:
        """Log the approval request and move the run from `running` to `interrupted`."""
        try:
            await self._store.add_pending_approval(
                user_id, conversation_id, run_id, reason=reason, options=options
            )
            moved = await self._store.transition_run(
                user_id,
                run_id,
                from_status="running",
                changes={"status": "interrupted", **progress.model_dump()},
            )
            if not moved:
                raise ConflictError("The run is no longer running.")
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise

    async def resume_run(self, user_id: UUID, run_id: UUID, decision: str) -> ResumedRun:
        """Record the user's decision and move the run from `interrupted` back to `running`.

        A missing or non-owned run is not found; a run that is not waiting for approval (or
        was resumed by a concurrent request) is a conflict; a decision that was not offered is
        invalid.
        """
        try:
            run = await self._store.get_run(user_id, run_id)
            if run is None:
                raise NotFoundError("Run not found.")
            approval = await self._store.get_pending_approval(user_id, run_id)
            if run.status != "interrupted" or approval is None or run.conversation_id is None:
                raise ConflictError("The run is not waiting for an approval decision.")
            if decision not in approval.options:
                raise InvalidInputError(
                    f"Decision {decision!r} was not offered.",
                    details={"options": approval.options},
                )
            moved = await self._store.transition_run(
                user_id, run_id, from_status="interrupted", changes={"status": "running"}
            )
            if not moved or not await self._store.decide_approval(user_id, approval.id, decision):
                raise ConflictError("The run is not waiting for an approval decision.")
            result = ResumedRun(
                run_id=run.id,
                conversation_id=run.conversation_id,
                workspace_id=run.workspace_id,
                decision=cast(MessageMode, decision),
                progress=RunProgress(
                    latency_ms=run.latency_ms or 0, llm_calls=run.llm_calls, tokens=run.tokens
                ),
            )
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise
        return result

    async def get_run(self, user_id: UUID, run_id: UUID) -> RunInfo:
        """The run's state and, while it is paused, the approval request it waits on."""
        run = await self._store.get_run(user_id, run_id)
        if run is None:
            raise NotFoundError("Run not found.")
        pending = None
        if run.status == "interrupted":
            approval = await self._store.get_pending_approval(user_id, run_id)
            if approval is not None:
                pending = PendingApproval(reason=approval.reason, options=approval.options)
        return RunInfo(
            id=run.id,
            conversation_id=run.conversation_id,
            status=cast(RunStatus, run.status),
            error=run.error,
            created_at=run.created_at,
            finished_at=run.finished_at,
            pending_approval=pending,
        )

    async def fail_run(self, user_id: UUID, run_id: UUID, summary: RunSummary) -> None:
        """Finish the run as failed in its own transaction (it may have been in any state)."""
        try:
            await self._store.finish_run(
                user_id, run_id, summary.model_copy(update={"status": "failed"}).model_dump()
            )
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise

    async def fail_stale_runs(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int:
        """Fail `running` runs left behind by a restart; returns the count."""
        try:
            count = await self._store.fail_stale_runs(
                older_than=older_than, reason=reason, exclude=exclude
            )
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise
        return count

    async def save_answer(
        self,
        user_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        answer: AnswerDraft,
        summary: RunSummary,
    ) -> MessageRead:
        """Store the answer, its claims, evidence, and citations, and finish the run.

        All in one transaction: if any part fails, nothing is saved.
        """
        message = _answer_message(conversation_id, run_id, answer)
        try:
            saved = await self._store.save_answer(user_id, message, run_id, summary.model_dump())
            if saved is None:
                raise NotFoundError("Conversation or run not found.")
            result = MessageRead.model_validate(saved)
            await self._store.commit()
        except Exception:
            await self._store.rollback()
            raise
        return result

    async def _owned_workspace(self, user_id: UUID, workspace_id: UUID) -> Workspace:
        workspace = await self._store.get_workspace(user_id, workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        return workspace

    async def _owned_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self._store.get(user_id, conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation


def _answer_message(conversation_id: UUID, run_id: UUID, answer: AnswerDraft) -> Message:
    """Build the assistant message with its claims, evidence, and citations attached."""
    return Message(
        conversation_id=conversation_id,
        role="assistant",
        content=answer.content,
        mode=answer.mode,
        run_id=run_id,
        claims=[
            Claim(
                position=position,
                text=claim.text,
                status=claim.status,
                support_score=claim.support_score,
                evidence=[Evidence(**e.model_dump()) for e in claim.evidence],
                citations=[Citation(**c.model_dump()) for c in claim.citations],
            )
            for position, claim in enumerate(answer.claims)
        ],
    )
