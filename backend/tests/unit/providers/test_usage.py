import asyncio

from app.providers.fakes import FakeLLM
from app.providers.llm import ChatMessage, TokenUsage
from app.providers.usage import record_call, record_failed_attempt, track_usage

MESSAGES = [ChatMessage(role="user", content="one two three")]


def test_calls_outside_a_scope_are_not_counted_anywhere() -> None:
    record_call("m", TokenUsage(input_tokens=1, output_tokens=1))

    with track_usage() as usage:
        pass

    assert usage.calls == 0


async def test_scope_counts_calls_tokens_and_models() -> None:
    fast = FakeLLM(model_name="fast")
    strong = FakeLLM(model_name="strong")

    with track_usage() as usage:
        await fast.generate_text(MESSAGES)
        await strong.generate_text(MESSAGES)
        await strong.generate_text(MESSAGES)
        record_failed_attempt()

    assert usage.calls == 3
    assert usage.input_tokens == 9
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens
    assert usage.by_model["strong"].calls == 2
    assert usage.by_model["fast"].calls == 1
    assert usage.failed_attempts == 1


async def test_nested_scopes_both_count_and_close_independently() -> None:
    llm = FakeLLM()

    with track_usage() as outer:
        await llm.generate_text(MESSAGES)
        with track_usage() as inner:
            await llm.generate_text(MESSAGES)
        await llm.generate_text(MESSAGES)

    assert outer.calls == 3
    assert inner.calls == 1


async def test_calls_in_child_tasks_count_and_concurrent_runs_stay_separate() -> None:
    llm = FakeLLM()

    async def run(calls: int) -> int:
        with track_usage() as usage:
            await asyncio.gather(*(llm.generate_text(MESSAGES) for _ in range(calls)))
        return usage.calls

    assert await asyncio.gather(run(2), run(5)) == [2, 5]
