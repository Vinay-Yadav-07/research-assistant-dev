"""Benchmark runs and their per-question results (FR-27, SRS §17)."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import CreatedAt, UUIDPrimaryKey
from app.models.base import Base


class EvalRun(Base):
    """One evaluation of a condition (C1–C5) on a dataset version; written by the eval CLI."""

    __tablename__ = "eval_runs"

    id: Mapped[UUIDPrimaryKey]
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dataset_version: Mapped[str] = mapped_column(Text, nullable=False)
    # Null until the run finishes.
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[CreatedAt]


class EvalResult(Base):
    """One benchmark question's output and scores within an evaluation run."""

    __tablename__ = "eval_results"
    __table_args__ = (UniqueConstraint("eval_run_id", "question_id"),)

    id: Mapped[UUIDPrimaryKey]
    eval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    # The benchmark item id from `backend/eval/data/`.
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[CreatedAt]
