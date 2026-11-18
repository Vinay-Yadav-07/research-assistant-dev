"""Eval run repository SQL against a migrated database (FR-27).

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back; the repository's commits only touch a savepoint.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.eval_run import EvalResult, EvalRun
from app.repositories.database import create_engine_from_settings
from app.repositories.eval_runs import EvalRunRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    engine = create_engine_from_settings(Settings())
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as db:
                    yield db
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_run_results_and_metrics_are_stored(session: AsyncSession) -> None:
    repo = EvalRunRepository(session)

    run_id = await repo.create_run("C2", {"top_k": 8}, "benchmark_v1")
    await repo.add_result(run_id, "test-001", {"answer": "A."}, {"R@8": 1.0})
    await repo.add_result(run_id, "test-002", {"answer": "B."}, {"R@8": 0.0})
    unfinished = await session.scalar(select(EvalRun.metrics_json).where(EvalRun.id == run_id))
    await repo.finish_run(run_id, {"retrieval": {"R@8": 0.5}})

    run = await session.scalar(
        select(EvalRun).where(EvalRun.id == run_id).execution_options(populate_existing=True)
    )
    assert unfinished is None
    assert run is not None
    assert (run.condition, run.config_json, run.dataset_version) == (
        "C2",
        {"top_k": 8},
        "benchmark_v1",
    )
    assert run.metrics_json == {"retrieval": {"R@8": 0.5}}
    results = (
        await session.scalars(
            select(EvalResult)
            .where(EvalResult.eval_run_id == run_id)
            .order_by(EvalResult.question_id)
        )
    ).all()
    assert [(r.question_id, r.scores_json) for r in results] == [
        ("test-001", {"R@8": 1.0}),
        ("test-002", {"R@8": 0.0}),
    ]


async def test_a_question_is_recorded_once_per_run(session: AsyncSession) -> None:
    repo = EvalRunRepository(session)
    run_id = await repo.create_run("C1", {}, "benchmark_v1")
    await repo.add_result(run_id, "test-001", {}, {})

    with pytest.raises(IntegrityError):
        await repo.add_result(run_id, "test-001", {}, {})


async def test_results_of_an_unknown_run_are_rejected(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await EvalRunRepository(session).add_result(uuid4(), "test-001", {}, {})
