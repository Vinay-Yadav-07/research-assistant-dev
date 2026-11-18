"""Runs the QA graph for a conversation and records each run (FR-25, FR-28, NFR-05, NFR-13).

`start` stores the question and a `running` run, `resume` records the user's approval decision;
both return a `QARun` whose `events()` yield progress, the approval request, or the saved
answer. The graph executes in its own task, so a client that stops listening does not stop the
run: its answer is still saved and appears in the conversation history. LLM calls, tokens, and
processing time are counted per segment (a run paused for approval has two) and stored on
`agent_runs`. Any failure marks the run `failed` in a transaction of its own. Only a paused run
keeps its checkpoints; a finished or failed run's are deleted.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.graphs.qa import WORKFLOW, Outcome, QAContext, QAState, Stage, initial_state, outcome_of
from app.providers.usage import track_usage
from app.schemas.conversations import CitationRead, ClaimRead, MessageRead, RunStatus
from app.services.conversations import ConversationService, RunProgress, RunSummary
from app.services.guardrails import check_question
from app.services.knowledge_boundary import ApprovalRequest

logger = logging.getLogger(__name__)

# Supersteps: analyze, up to 4 retrieval waves with their joins, S3, S4, external research,
# 1 + max revisions of A2 and A3, and finalize. Comfortably above that for 2 revisions.
RECURSION_LIMIT = 50
STALE_RUN_REASON = "The run was interrupted by a server restart."
_INTERNAL_ERROR = "internal_error"


class StatusEvent(BaseModel):
    """The run entered a stage (SRS §7.1)."""

    type: Literal["status"] = "status"
    stage: Stage


class ApprovalRequiredEvent(BaseModel):
    """The run paused; resume it with one of the offered options (SRS §7.2)."""

    type: Literal["approval_required"] = "approval_required"
    run_id: UUID
    request: ApprovalRequest


class ClaimsEvent(BaseModel):
    """The saved answer's verified claims, with their evidence and citations."""

    type: Literal["claims"] = "claims"
    message_id: UUID
    claims: list[ClaimRead]


class CitationsEvent(BaseModel):
    """Every citation of the saved answer, in claim order."""

    type: Literal["citations"] = "citations"
    message_id: UUID
    citations: list[CitationRead]


class ErrorEvent(BaseModel):
    """The run failed; it is marked `failed`."""

    type: Literal["error"] = "error"
    run_id: UUID
    code: str
    message: str


class DoneEvent(BaseModel):
    """The run finished and its answer (or abstention, or refusal) is saved."""

    type: Literal["done"] = "done"
    run_id: UUID
    outcome: Outcome
    message: MessageRead


class RunRead(BaseModel):
    """A run's state; `approval` is the request a paused (`interrupted`) run waits on, so a
    reloaded conversation can show it again and resume (SRS §20)."""

    id: UUID
    conversation_id: UUID | None
    status: RunStatus
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    approval: ApprovalRequest | None


QAEvent = Annotated[
    StatusEvent | ApprovalRequiredEvent | ClaimsEvent | CitationsEvent | ErrorEvent | DoneEvent,
    Field(discriminator="type"),
]

ConversationOpener = Callable[[], AbstractAsyncContextManager[ConversationService]]
QAGraph = CompiledStateGraph[QAState, QAContext, QAState, QAState]


@dataclass(frozen=True)
class QARun:
    """A started or resumed run and the stream of its events."""

    run_id: UUID
    conversation_id: UUID
    _queue: "asyncio.Queue[QAEvent | None]"
    _task: "asyncio.Task[None]"

    async def events(self) -> AsyncIterator[QAEvent]:
        """Events until the run finishes, fails, or pauses for approval.

        When the stream ends, the run's state is stored and its task is done.
        """
        while (event := await self._queue.get()) is not None:
            yield event
        await self._task


class QARunner:
    """Starts and resumes QA runs; one per application."""

    def __init__(
        self,
        graph: QAGraph,
        context: QAContext,
        conversations: ConversationOpener,
        *,
        max_question_chars: int,
    ) -> None:
        self._graph = graph
        self._context = context
        self._conversations = conversations
        self._max_question_chars = max_question_chars
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def start(self, user_id: UUID, conversation_id: UUID, question: str) -> QARun:
        """Ask `question` in one of the user's conversations.

        Raises before anything is stored if the question fails the S6 input check, and
        `NotFoundError` for a missing or non-owned conversation.
        """
        question = check_question(question, self._max_question_chars)
        async with self._conversations() as service:
            started = await service.begin_run(
                user_id, conversation_id, question=question, workflow=WORKFLOW
            )
        graph_input = initial_state(
            run_id=started.run_id,
            user_id=user_id,
            workspace_id=started.workspace_id,
            question=question,
            conversation_mode=started.conversation_mode,
        )
        return self._launch(user_id, started.run_id, conversation_id, graph_input, RunProgress())

    async def resume(self, user_id: UUID, run_id: UUID, decision: str) -> QARun:
        """Continue a paused run with the user's decision.

        Raises `NotFoundError` for a missing or non-owned run, `ConflictError` when the run is
        not waiting for approval, and `InvalidInputError` for a decision that was not offered.
        """
        async with self._conversations() as service:
            resumed = await service.resume_run(user_id, run_id, decision)
        return self._launch(
            user_id,
            run_id,
            resumed.conversation_id,
            Command(resume=resumed.decision),
            resumed.progress,
        )

    async def get_run(self, user_id: UUID, run_id: UUID) -> RunRead:
        """The run's state; raises `NotFoundError` for a missing or non-owned run.

        A paused run's approval request comes from its checkpoint, which also holds the
        per-sub-question coverage; without one, the logged reason and options are returned.
        """
        async with self._conversations() as service:
            run = await service.get_run(user_id, run_id)
        approval = None
        if run.pending_approval is not None:
            approval = await self._pending_request(run_id) or ApprovalRequest(
                reason=run.pending_approval.reason,
                options=run.pending_approval.options,
                sub_questions=[],
            )
        return RunRead(**run.model_dump(exclude={"pending_approval"}), approval=approval)

    async def fail_stale(self, older_than: timedelta) -> int:
        """Fail `running` runs older than `older_than` that this process is not executing."""
        async with self._conversations() as service:
            count = await service.fail_stale_runs(
                older_than=older_than, reason=STALE_RUN_REASON, exclude=set(self._tasks)
            )
        if count:
            logger.warning("Marked %d interrupted QA run(s) as failed", count)
        return count

    async def sweep_periodically(self, interval_seconds: float, older_than: timedelta) -> None:
        """Run `fail_stale` every `interval_seconds` until cancelled; errors are logged."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.fail_stale(older_than)
            except Exception:
                logger.exception("Periodic sweep of stale QA runs failed")

    async def aclose(self) -> None:
        """Cancel runs still executing (the sweep fails them after a restart)."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _launch(
        self,
        user_id: UUID,
        run_id: UUID,
        conversation_id: UUID,
        graph_input: QAState | Command[Any],
        base: RunProgress,
    ) -> QARun:
        queue: asyncio.Queue[QAEvent | None] = asyncio.Queue()
        task = asyncio.create_task(
            self._execute(user_id, run_id, conversation_id, graph_input, base, queue)
        )
        self._tasks[run_id] = task
        return QARun(run_id=run_id, conversation_id=conversation_id, _queue=queue, _task=task)

    async def _execute(
        self,
        user_id: UUID,
        run_id: UUID,
        conversation_id: UUID,
        graph_input: QAState | Command[Any],
        base: RunProgress,
        queue: "asyncio.Queue[QAEvent | None]",
    ) -> None:
        config: RunnableConfig = {
            "configurable": {"thread_id": str(run_id)},
            "recursion_limit": RECURSION_LIMIT,
            "run_name": WORKFLOW,
            "metadata": {"agent_run_id": str(run_id), "conversation_id": str(conversation_id)},
        }
        started = time.perf_counter()
        request: ApprovalRequest | None = None
        with track_usage() as usage:

            def progress() -> RunProgress:
                return RunProgress(
                    latency_ms=base.latency_ms + round((time.perf_counter() - started) * 1000),
                    llm_calls=base.llm_calls + usage.calls,
                    tokens=base.tokens + usage.total_tokens,
                )

            try:
                stage: str | None = None
                async for part in self._graph.astream(
                    graph_input,
                    config,
                    context=self._context,
                    stream_mode=["custom", "updates"],
                ):
                    mode, chunk = cast(tuple[str, dict[str, Any]], part)
                    if mode == "custom" and chunk["stage"] != stage:
                        stage = chunk["stage"]
                        await queue.put(StatusEvent.model_validate(chunk))
                    elif mode == "updates" and "__interrupt__" in chunk:
                        request = ApprovalRequest.model_validate(chunk["__interrupt__"][0].value)
                if request is not None:
                    async with self._conversations() as service:
                        await service.pause_run(
                            user_id,
                            run_id,
                            conversation_id,
                            reason=request.reason,
                            options=list(request.options),
                            progress=progress(),
                        )
                    await queue.put(ApprovalRequiredEvent(run_id=run_id, request=request))
                    return
                outcome, answer = outcome_of(dict((await self._graph.aget_state(config)).values))
                async with self._conversations() as service:
                    message = await service.save_answer(
                        user_id,
                        conversation_id,
                        run_id,
                        answer,
                        RunSummary(status="completed", **progress().model_dump()),
                    )
                    claims = await service.list_claims(user_id, message.id)
                await queue.put(ClaimsEvent(message_id=message.id, claims=claims))
                await queue.put(
                    CitationsEvent(
                        message_id=message.id,
                        citations=[citation for claim in claims for citation in claim.citations],
                    )
                )
                await queue.put(DoneEvent(run_id=run_id, outcome=outcome, message=message))
            except Exception as error:
                request = None
                await queue.put(await self._fail(user_id, run_id, error, progress()))
            finally:
                self._tasks.pop(run_id, None)
                if request is None:
                    await self._forget(run_id)
                await queue.put(None)

    async def _pending_request(self, run_id: UUID) -> ApprovalRequest | None:
        """The approval request saved in a paused run's checkpoint, or None."""
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": str(run_id)}})
        if not snapshot.interrupts:
            return None
        return ApprovalRequest.model_validate(snapshot.interrupts[0].value)

    async def _forget(self, run_id: UUID) -> None:
        """Delete a finished run's checkpoints.

        They hold chunk text, and only a paused run is ever resumed; the answer and its records
        are in the conversation.
        """
        checkpointer = self._graph.checkpointer
        if not isinstance(checkpointer, BaseCheckpointSaver):
            return
        try:
            await checkpointer.adelete_thread(str(run_id))
        except Exception:
            logger.exception("Could not delete the checkpoints of QA run %s", run_id)

    async def _fail(
        self, user_id: UUID, run_id: UUID, error: Exception, progress: RunProgress
    ) -> ErrorEvent:
        """Mark the run failed (separately from anything that rolled back) and describe it."""
        if isinstance(error, AppError):
            code, message = error.code, error.message
            logger.warning("QA run %s failed: %s", run_id, code)
        else:
            code, message = _INTERNAL_ERROR, "The run failed unexpectedly."
            logger.exception("QA run %s failed", run_id)
        summary = RunSummary(status="failed", error=f"{code}: {message}", **progress.model_dump())
        try:
            async with self._conversations() as service:
                await service.fail_run(user_id, run_id, summary)
        except Exception:
            logger.exception("Could not mark QA run %s as failed", run_id)
        return ErrorEvent(run_id=run_id, code=code, message=message)
