"""In-memory stand-in for `ConversationRepository`, shared by the API and service tests."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.models.agent_run import AgentRun
from app.models.conversation import Approval, Claim, Conversation, Message
from app.models.workspace import Workspace


class InMemoryConversationStore:
    """Mirrors `ConversationRepository`'s ownership rules without a database."""

    def __init__(self) -> None:
        self.workspaces: dict[UUID, Workspace] = {}
        self.conversations: dict[UUID, Conversation] = {}
        self.messages: dict[UUID, Message] = {}
        self.approvals: list[Approval] = []
        self.runs: dict[UUID, AgentRun] = {}
        self.stale_sweeps: list[tuple[timedelta, set[UUID]]] = []
        self.commits = 0
        self.rollbacks = 0
        self._tick = datetime(2026, 1, 1, tzinfo=UTC)

    def _now(self) -> datetime:
        self._tick += timedelta(seconds=1)
        return self._tick

    def add_workspace(self, user_id: UUID, default_mode: str = "corpus_only") -> Workspace:
        workspace = Workspace(id=uuid4(), user_id=user_id, name="W", default_mode=default_mode)
        self.workspaces[workspace.id] = workspace
        return workspace

    async def get_workspace(self, user_id: UUID, workspace_id: UUID) -> Workspace | None:
        row = self.workspaces.get(workspace_id)
        return row if row is not None and row.user_id == user_id else None

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        rows = [
            c
            for c in self.conversations.values()
            if c.workspace_id == workspace_id and c.user_id == user_id
        ]
        rows.sort(key=lambda c: c.updated_at, reverse=True)
        return rows[offset : offset + limit]

    async def create(
        self, user_id: UUID, workspace_id: UUID, *, title: str | None, mode: str
    ) -> Conversation:
        now = self._now()
        row = Conversation(
            id=uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            title=title,
            mode=mode,
            created_at=now,
            updated_at=now,
        )
        self.conversations[row.id] = row
        return row

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        row = self.conversations.get(conversation_id)
        return row if row is not None and row.user_id == user_id else None

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[Message]:
        if await self.get(user_id, conversation_id) is None:
            return []
        rows = [m for m in self.messages.values() if m.conversation_id == conversation_id]
        rows.sort(key=lambda m: m.created_at)
        return rows[offset : offset + limit]

    async def get_message(self, user_id: UUID, message_id: UUID) -> Message | None:
        row = self.messages.get(message_id)
        if row is None or await self.get(user_id, row.conversation_id) is None:
            return None
        return row

    async def list_claims(self, user_id: UUID, message_id: UUID) -> list[Claim]:
        message = await self.get_message(user_id, message_id)
        return [] if message is None else sorted(message.claims, key=lambda c: c.position)

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
        approval = Approval(
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            options=options,
            decision=decision,
            decided_at=self._now(),
        )
        self.approvals.append(approval)
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
        approval = Approval(
            id=uuid4(),
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            options=options,
            created_at=self._now(),
        )
        self.approvals.append(approval)
        return approval

    async def get_pending_approval(self, user_id: UUID, run_id: UUID) -> Approval | None:
        pending = [
            a
            for a in self.approvals
            if a.run_id == run_id and a.user_id == user_id and a.decision is None
        ]
        return pending[-1] if pending else None

    async def decide_approval(self, user_id: UUID, approval_id: UUID, decision: str) -> bool:
        for approval in self.approvals:
            if approval.id == approval_id and approval.user_id == user_id:
                if approval.decision is not None:
                    return False
                approval.decision = decision
                approval.decided_at = self._now()
                return True
        return False

    async def get_run(self, user_id: UUID, run_id: UUID) -> AgentRun | None:
        run = self.runs.get(run_id)
        return run if run is not None and run.user_id == user_id else None

    async def transition_run(
        self, user_id: UUID, run_id: UUID, *, from_status: str, changes: dict[str, object]
    ) -> bool:
        run = await self.get_run(user_id, run_id)
        if run is None or run.status != from_status:
            return False
        for field, value in changes.items():
            setattr(run, field, value)
        return True

    async def finish_run(self, user_id: UUID, run_id: UUID, changes: dict[str, object]) -> bool:
        run = await self.get_run(user_id, run_id)
        if run is None:
            return False
        for field, value in changes.items():
            setattr(run, field, value)
        run.finished_at = self._now()
        return True

    async def fail_stale_runs(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int:
        self.stale_sweeps.append((older_than, set(exclude)))
        stale = [
            run for run in self.runs.values() if run.status == "running" and run.id not in exclude
        ]
        for run in stale:
            run.status, run.error = "failed", reason
        return len(stale)

    async def create_run(
        self, user_id: UUID, workspace_id: UUID, conversation_id: UUID | None, *, workflow: str
    ) -> AgentRun:
        run = AgentRun(
            id=uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            workflow=workflow,
            status="running",
            llm_calls=0,
            tokens=0,
            created_at=self._now(),
        )
        self.runs[run.id] = run
        return run

    async def add_message(self, user_id: UUID, message: Message) -> Message | None:
        conversation = await self.get(user_id, message.conversation_id)
        if conversation is None:
            return None
        message.id = uuid4()
        message.created_at = conversation.updated_at = self._now()
        for claim in message.claims:
            claim.id = uuid4()
            for item in (*claim.evidence, *claim.citations):
                item.id = uuid4()
        self.messages[message.id] = message
        return message

    async def save_answer(
        self, user_id: UUID, message: Message, run_id: UUID, run_changes: dict[str, object]
    ) -> Message | None:
        if not await self.finish_run(user_id, run_id, run_changes):
            return None
        return await self.add_message(user_id, message)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1
