"""The QA graph's Postgres checkpointer against a migrated database (SRS §5.4, §14.1).

A run paused for approval is resumed by a new pool and a new graph, as after a restart, and
the `langgraph` schema stays closed to the client roles. Runs in CI's pgvector container after
`scripts/setup_checkpointer.py`, and against Supabase dev. Run data stays in memory; only the
checkpoints are written, and each test deletes its thread.
"""

from collections.abc import AsyncIterator

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text

from app.agents.query_analyzer import QueryPlan
from app.agents.synthesis import DraftAnswer
from app.core.config import Settings
from app.graphs.qa_runner import ApprovalRequiredEvent, DoneEvent
from app.models.migration_scope import CHECKPOINT_TABLES
from app.repositories.checkpoints import (
    CheckpointPool,
    create_checkpoint_pool,
    create_checkpointer,
)
from app.repositories.database import create_engine_from_settings
from tests.unit.graphs.qa_harness import UNANSWERABLE, collect, harness
from tests.unit.services.test_retrieval import USER

pytestmark = pytest.mark.integration


@pytest.fixture
async def pool() -> AsyncIterator[CheckpointPool]:
    """A fresh checkpoint pool per use, like the one the app opens at startup."""
    created = create_checkpoint_pool(Settings())
    if created is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    await created.open(wait=True, timeout=30)
    try:
        yield created
    finally:
        await created.close()


async def test_a_paused_run_resumes_after_a_restart(pool: CheckpointPool) -> None:
    h = await harness(corpus=(), checkpointer=create_checkpointer(pool))
    h.fast.script(QueryPlan, QueryPlan(intent="simple_qa"))
    run = await h.runner.start(USER, h.conversation_id, UNANSWERABLE)
    paused = (await collect(run))[-1]
    assert isinstance(paused, ApprovalRequiredEvent)

    restarted_pool = create_checkpoint_pool(Settings())
    assert restarted_pool is not None
    await restarted_pool.open(wait=True, timeout=30)
    try:
        restarted = await harness(corpus=(), checkpointer=create_checkpointer(restarted_pool))
        restarted.store.runs = h.store.runs
        restarted.store.approvals = h.store.approvals
        restarted.store.conversations = h.store.conversations
        restarted.strong.script(
            DraftAnswer,
            DraftAnswer.model_validate(
                {"sentences": [{"text": "Bioreactors are costly.", "kind": "general"}]}
            ),
        )

        # A reloaded page reads the full request, coverage included, back from the checkpoint.
        reloaded = await restarted.runner.get_run(USER, run.run_id)
        assert (reloaded.status, reloaded.approval) == ("interrupted", paused.request)

        events = await collect(await restarted.runner.resume(USER, run.run_id, "general_knowledge"))

        finished = events[-1]
        assert isinstance(finished, DoneEvent)
        assert (finished.outcome, finished.message.mode) == ("answered", "general_knowledge")
        # The restarted graph never re-ran A1: the plan came from the checkpoint.
        assert restarted.fast.calls == []
    finally:
        await create_checkpointer(restarted_pool).adelete_thread(str(run.run_id))
        await restarted_pool.close()


async def test_paused_state_is_plain_json_and_finished_runs_are_deleted(
    pool: CheckpointPool,
) -> None:
    checkpointer = create_checkpointer(pool)
    h = await harness(corpus=(), checkpointer=checkpointer)
    h.fast.script(QueryPlan, QueryPlan(intent="simple_qa"))
    run = await h.runner.start(USER, h.conversation_id, UNANSWERABLE)
    config: RunnableConfig = {"configurable": {"thread_id": str(run.run_id)}}
    try:
        assert isinstance((await collect(run))[-1], ApprovalRequiredEvent)
        saved = await checkpointer.aget_tuple(config)
        assert saved is not None
        values = saved.checkpoint["channel_values"]
        assert isinstance(values["plan"], dict) and isinstance(values["sufficiency"], dict)

        done = (await collect(await h.runner.resume(USER, run.run_id, "corpus_only")))[-1]

        assert isinstance(done, DoneEvent) and done.outcome == "abstained"
        assert await checkpointer.aget_tuple(config) is None
    finally:
        await checkpointer.adelete_thread(str(run.run_id))


async def test_langgraph_schema_is_closed_to_client_roles() -> None:
    engine = create_engine_from_settings(Settings())
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        async with engine.connect() as connection:
            usage = await connection.execute(
                text(
                    "SELECT role, has_schema_privilege(role, 'langgraph', 'USAGE') "
                    "FROM unnest(ARRAY['anon', 'authenticated']) AS role"
                )
            )
            assert {role: allowed for role, allowed in usage} == {
                "anon": False,
                "authenticated": False,
            }
            tables = await connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'langgraph' AND c.relkind = 'r'"
                )
            )
            assert {name: rls for name, rls in tables} == dict.fromkeys(CHECKPOINT_TABLES, True)
    finally:
        await engine.dispose()
