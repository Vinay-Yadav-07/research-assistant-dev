"""Chat history, agent run, and approval persistence. Every read filters by the owning `user_id`."""

from collections.abc import Collection
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent_run import AgentRun
from app.models.conversation import Approval, Claim, Conversation, Message
from app.models.workspace import Workspace


class ConversationRepository:
    """Reads and writes one user's conversations within the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_workspace(self, user_id: UUID, workspace_id: UUID) -> Workspace | None:
        """The workspace, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(Workspace).where(Workspace.id == workspace_id, Workspace.user_id == user_id)
        )

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        """The workspace's conversations, most recently active first."""
        result = await self._session.scalars(
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id, Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def create(
        self, user_id: UUID, workspace_id: UUID, *, title: str | None, mode: str
    ) -> Conversation:
        """Insert a conversation; the caller has checked that the workspace is owned."""
        conversation = Conversation(
            user_id=user_id, workspace_id=workspace_id, title=title, mode=mode
        )
        self._session.add(conversation)
        await self._session.flush()
        await self._session.refresh(conversation)
        return conversation

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        """The conversation, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[Message]:
        """The conversation's messages, oldest first, with their claims, evidence, and citations.

        The claims load in a fixed number of extra queries, however many messages there are.
        """
        claims = selectinload(Message.claims)
        result = await self._session.scalars(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.conversation_id == conversation_id, Conversation.user_id == user_id)
            .order_by(Message.created_at, Message.id)
            .limit(limit)
            .offset(offset)
            .options(claims.selectinload(Claim.evidence), claims.selectinload(Claim.citations))
        )
        return list(result)

    async def get_message(self, user_id: UUID, message_id: UUID) -> Message | None:
        """The message, or None if it is missing or in another user's conversation."""
        return await self._session.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.user_id == user_id)
        )

    async def list_claims(self, user_id: UUID, message_id: UUID) -> list[Claim]:
        """The message's claims in answer order, with their evidence and citations."""
        result = await self._session.scalars(
            select(Claim)
            .join(Message, Message.id == Claim.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Claim.message_id == message_id, Conversation.user_id == user_id)
            .order_by(Claim.position)
            .options(selectinload(Claim.evidence), selectinload(Claim.citations))
        )
        return list(result)

    async def add_approval(
        self,
        user_id: UUID,
        conversation_id: UUID,
        *,
        reason: str,
        options: list[str],
        decision: str,
        run_id: UUID | None = None,
    ) -> Approval:
        """Log an approval decided now (SRS §10.3)."""
        approval = Approval(
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            options=options,
            decision=decision,
            decided_at=func.now(),
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    async def add_pending_approval(
        self,
        user_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        *,
        reason: str,
        options: list[str],
    ) -> Approval:
        """Log an approval request the run now waits on; the decision comes later."""
        approval = Approval(
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            options=options,
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    async def get_pending_approval(self, user_id: UUID, run_id: UUID) -> Approval | None:
        """The run's undecided approval request, or None."""
        return await self._session.scalar(
            select(Approval)
            .where(
                Approval.run_id == run_id,
                Approval.user_id == user_id,
                Approval.decision.is_(None),
            )
            .order_by(Approval.created_at.desc(), Approval.id)
            .limit(1)
        )

    async def decide_approval(self, user_id: UUID, approval_id: UUID, decision: str) -> bool:
        """Record the decision on an undecided request; False if none was updated."""
        decided = await self._session.scalar(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.user_id == user_id,
                Approval.decision.is_(None),
            )
            .values(decision=decision, decided_at=func.now())
            .returning(Approval.id)
        )
        return decided is not None

    async def get_run(self, user_id: UUID, run_id: UUID) -> AgentRun | None:
        """The run, or None if it is missing or owned by someone else."""
        return await self._session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )

    async def transition_run(
        self, user_id: UUID, run_id: UUID, *, from_status: str, changes: dict[str, object]
    ) -> bool:
        """Apply `changes` only if the owned run is in `from_status`; False otherwise.

        One conditional UPDATE, so two concurrent transitions cannot both succeed.
        """
        moved = await self._session.scalar(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
                AgentRun.status == from_status,
            )
            .values(**changes)
            .returning(AgentRun.id)
        )
        return moved is not None

    async def fail_stale_runs(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int:
        """Mark `running` runs created before `older_than` as failed; returns the count.

        `exclude` holds runs the caller is still executing. A system-wide sweep, so it is not
        scoped to one user. `interrupted` runs are never touched: they wait for the user.
        """
        conditions = [
            AgentRun.status == "running",
            AgentRun.created_at < func.now() - older_than,
        ]
        if exclude:
            conditions.append(AgentRun.id.not_in(list(exclude)))
        result = await self._session.execute(
            update(AgentRun)
            .where(*conditions)
            .values(status="failed", error=reason, finished_at=func.now())
            .returning(AgentRun.id)
        )
        return len(result.all())

    async def create_run(
        self, user_id: UUID, workspace_id: UUID, conversation_id: UUID | None, *, workflow: str
    ) -> AgentRun:
        """Insert a run in the `running` state."""
        run = AgentRun(
            user_id=user_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            workflow=workflow,
        )
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def add_message(self, user_id: UUID, message: Message) -> Message | None:
        """Insert `message` with any claims attached and mark its conversation active.

        Returns None, inserting nothing, if the conversation is missing or not owned.
        """
        touched = await self._session.scalar(
            update(Conversation)
            .where(Conversation.id == message.conversation_id, Conversation.user_id == user_id)
            .values(updated_at=func.now())
            .returning(Conversation.id)
        )
        if touched is None:
            return None
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message, ["created_at"])
        return message

    async def finish_run(self, user_id: UUID, run_id: UUID, changes: dict[str, object]) -> bool:
        """Apply `changes` to an owned run and stamp `finished_at`; False if it is not found."""
        finished = await self._session.scalar(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.user_id == user_id)
            .values(**changes, finished_at=func.now())
            .returning(AgentRun.id)
        )
        return finished is not None

    async def save_answer(
        self, user_id: UUID, message: Message, run_id: UUID, run_changes: dict[str, object]
    ) -> Message | None:
        """Finish the run and insert the answer with its claims, evidence, and citations.

        Nothing is committed here. Returns None if the run or conversation is missing or not
        owned; the caller must then roll back, because the run may already be updated.
        """
        if not await self.finish_run(user_id, run_id, run_changes):
            return None
        return await self.add_message(user_id, message)

    async def commit(self) -> None:
        """Commit the session's transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the session's transaction."""
        await self._session.rollback()
