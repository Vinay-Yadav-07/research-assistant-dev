"""One execution of an agentic workflow, with its cost summary (FR-28, SRS §14.1)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import CreatedAt, UUIDPrimaryKey, one_of
from app.models.base import Base

# `interrupted` waits for an approval decision (S4); the checkpointer keeps its state.
RUN_STATUSES = ("running", "interrupted", "completed", "failed")


class AgentRun(Base):
    """A workflow run; its id is also the LangGraph thread id."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(one_of("status", RUN_STATUSES), name="status_valid"),
        Index("ix_agent_runs_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[UUIDPrimaryKey]
    # Supabase `auth.users.id`; no FK because `auth` is outside Alembic's scope (D-041).
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # Null for workflows outside a conversation (e.g. a literature review).
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    workflow: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    trace_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
