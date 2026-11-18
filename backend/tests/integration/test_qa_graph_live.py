"""The whole QA graph live on Supabase dev: real models, Groq (A1), Gemini (S3, A2, A3 judge).

One benchmark corpus is ingested into a fresh workspace. Three answerable calibration questions
must end answered (or abstained) with every claim cited and the run completed; one unanswerable
question must pause for approval and abstain after the user stays corpus-only. Latency and LLM
calls per question are printed (NFR-01, NFR-13). Run with `-s` to see the table. About 2-4 min
and up to ~20 LLM calls.
"""

import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graphs.qa_runner import (
    ApprovalRequiredEvent,
    ClaimsEvent,
    DoneEvent,
    QAEvent,
    QARun,
    StatusEvent,
)
from app.main import build_qa_runner
from app.models.agent_run import AgentRun
from app.repositories.checkpoints import create_checkpoint_pool
from app.repositories.conversations import ConversationRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.schemas.conversations import ConversationCreate
from app.services.conversations import ConversationService
from eval.dataset import BENCHMARK, load_items
from tests.integration.live_corpora import (
    available_corpora,
    corpus_workspace,
    live_providers,
    live_settings,
)

pytestmark = pytest.mark.integration

ANSWERABLE = 3


async def collect(run: QARun) -> tuple[list[QAEvent], float]:
    started = time.perf_counter()
    events = [event async for event in run.events()]
    return events, time.perf_counter() - started


async def test_questions_end_to_end() -> None:
    settings = live_settings().model_copy(update={"llm_fast_provider": "groq"})
    if settings.groq_api_key is None:
        pytest.skip("GROQ_API_KEY not set")
    engine = create_engine_from_settings(settings)
    pool = create_checkpoint_pool(settings)
    if engine is None or pool is None:
        pytest.skip("DATABASE_URL is not set")
    name, papers = next(iter(available_corpora().items()))
    items = [i for i in load_items(BENCHMARK, split="calibration") if i.corpus == name]
    answerable = [i for i in items if i.answerable][:ANSWERABLE]
    unanswerable = next(i for i in items if not i.answerable)
    providers = live_providers(settings)
    sessions = create_sessionmaker(engine)
    await pool.open(wait=True, timeout=30)
    runner = build_qa_runner(settings, providers, sessions, pool)
    user = uuid4()
    rows: list[tuple[str, str, float, int, int]] = []
    try:
        async with corpus_workspace(settings, providers, sessions, user, name, papers) as ws:
            async with sessions() as session:
                conversation = await ConversationService(ConversationRepository(session)).create(
                    user, ws, ConversationCreate(title="Live QA")
                )

            for item in answerable:
                run = await runner.start(user, conversation.id, item.question)
                events, seconds = await collect(run)
                done = events[-1]
                assert isinstance(done, DoneEvent), (item.id, done)
                assert done.outcome in ("answered", "abstained")
                assert isinstance(events[0], StatusEvent) and events[0].stage == "analyzing"
                claims = next(e for e in events if isinstance(e, ClaimsEvent)).claims
                assert all(c.citations for c in claims), item.id
                assert all(c.status != "unsupported" for c in claims), item.id
                rows.append((item.id, done.outcome, seconds, *(await usage(sessions, user, run))))

            run = await runner.start(user, conversation.id, unanswerable.question)
            events, first = await collect(run)
            paused = events[-1]
            assert isinstance(paused, ApprovalRequiredEvent), (unanswerable.id, paused)
            print(f"\n{unanswerable.id} approval reason: {paused.request.reason}")
            events, second = await collect(await runner.resume(user, run.run_id, "corpus_only"))
            done = events[-1]
            assert isinstance(done, DoneEvent) and done.outcome == "abstained", done
            print(f"{unanswerable.id} abstention: {done.message.content}")
            rows.append(
                (unanswerable.id, "abstained", first + second, *(await usage(sessions, user, run)))
            )
    finally:
        await runner.aclose()
        await pool.close()
        await engine.dispose()

    print(f"\n{'item':<10} {'outcome':<10} {'seconds':>8} {'LLM calls':>9} {'tokens':>7}")
    for item_id, outcome, seconds, calls, tokens in rows:
        print(f"{item_id:<10} {outcome:<10} {seconds:>8.1f} {calls:>9} {tokens:>7}")
    print(f"mean LLM calls per question: {sum(r[3] for r in rows) / len(rows):.1f}")


async def usage(
    sessions: async_sessionmaker[AsyncSession], user: UUID, run: QARun
) -> tuple[int, int]:
    """The run's stored LLM calls and tokens; the run must be completed."""
    async with sessions() as session:
        stored = await session.get(AgentRun, run.run_id)
        assert stored is not None and stored.user_id == user
        assert stored.status == "completed", stored.error
        return stored.llm_calls, stored.tokens
