import asyncio

import pytest

from app.core.errors import LLMQuotaExceededError
from app.providers.rate_limit import RateLimiter


class FakeClock:
    """Manual time; `sleep` advances it instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def limiter(clock: FakeClock, rpm: int = 0, tpm: int = 0, rpd: int = 0) -> RateLimiter:
    return RateLimiter(
        requests_per_minute=rpm,
        tokens_per_minute=tpm,
        requests_per_day=rpd,
        clock=clock,
        sleep=clock.sleep,
    )


async def test_requests_within_the_limit_do_not_wait() -> None:
    clock = FakeClock()
    rl = limiter(clock, rpm=3)

    for _ in range(3):
        await rl.acquire(10)

    assert clock.sleeps == []


async def test_request_over_the_limit_waits_for_the_oldest_to_leave_the_window() -> None:
    clock = FakeClock()
    rl = limiter(clock, rpm=2)
    await rl.acquire(1)
    clock.now = 10.0
    await rl.acquire(1)

    await rl.acquire(1)

    assert clock.sleeps == [60.0 - 10.0]
    assert clock.now == 60.0


async def test_token_limit_waits_until_enough_tokens_expire() -> None:
    clock = FakeClock()
    rl = limiter(clock, tpm=1000)
    await rl.acquire(600)
    clock.now = 5.0
    await rl.acquire(300)

    await rl.acquire(500)

    # Only after the 600-token request expires (t=60) do 300 + 500 fit.
    assert clock.now == 60.0


async def test_settle_replaces_the_estimate() -> None:
    clock = FakeClock()
    rl = limiter(clock, tpm=1000)
    reservation = await rl.acquire(900)
    reservation.settle(100)

    await rl.acquire(800)

    assert clock.sleeps == []


async def test_request_larger_than_the_token_limit_runs_once_the_window_is_empty() -> None:
    clock = FakeClock()
    rl = limiter(clock, tpm=100)
    await rl.acquire(50)

    await rl.acquire(5000)

    assert clock.now == 60.0


async def test_zero_disables_both_limits() -> None:
    clock = FakeClock()
    rl = limiter(clock)

    await asyncio.gather(*(rl.acquire(10_000) for _ in range(100)))

    assert clock.sleeps == []


async def test_daily_cap_raises_at_once_instead_of_waiting() -> None:
    clock = FakeClock()
    rl = limiter(clock, rpd=2)
    await rl.acquire(1)
    clock.now = 3600.0
    await rl.acquire(1)

    with pytest.raises(LLMQuotaExceededError) as caught:
        await rl.acquire(1)

    assert clock.sleeps == []
    assert caught.value.details == {"requests_per_day": 2}


async def test_daily_cap_frees_up_after_24_hours() -> None:
    clock = FakeClock()
    rl = limiter(clock, rpd=1)
    await rl.acquire(1)
    clock.now = 86_400.0

    await rl.acquire(1)

    assert clock.sleeps == []
