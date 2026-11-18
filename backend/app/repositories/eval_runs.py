"""Evaluation runs and per-question results (FR-27, SRS §17), written by the eval CLI.

Benchmark runs are not user data: the tables have no owner and no API reads them.
Each method commits, so a run interrupted halfway keeps the results recorded so far.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval_run import EvalResult, EvalRun


class EvalRunRepository:
    """Writes one run's configuration, results, and final metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self, condition: str, config: dict[str, Any], dataset_version: str
    ) -> UUID:
        """A new run without metrics; returns its id."""
        run = EvalRun(condition=condition, config_json=config, dataset_version=dataset_version)
        self._session.add(run)
        await self._session.commit()
        return run.id

    async def add_result(
        self, run_id: UUID, question_id: str, output: dict[str, Any], scores: dict[str, Any]
    ) -> None:
        """One question's output and scores (a question appears once per run)."""
        self._session.add(
            EvalResult(
                eval_run_id=run_id, question_id=question_id, output_json=output, scores_json=scores
            )
        )
        await self._session.commit()

    async def finish_run(self, run_id: UUID, metrics: dict[str, Any]) -> None:
        """Record the run's summary metrics."""
        await self._session.execute(
            update(EvalRun).where(EvalRun.id == run_id).values(metrics_json=metrics)
        )
        await self._session.commit()
