"""Client-side rate limiting for hosted LLM APIs (free tiers allow few requests per minute)."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.errors import LLMQuotaExceededError

WINDOW_SECONDS = 60.0
DAY_SECONDS = 86_400.0


@dataclass
class _Entry:
    at: float
    tokens: int


@dataclass
class Reservation:
    """A granted request; `settle` replaces its estimated tokens with the real count."""

    _entry: _Entry

    def settle(self, tokens: int) -> None:
        self._entry.tokens = max(tokens, 0)


class RateLimiter:
    """Sliding one-minute window over requests and tokens, plus a daily request cap.

    `acquire` waits until one more request with the estimated tokens fits. A single request
    larger than the token limit is let through once the window is empty, so it cannot block
    forever. When the rolling 24-hour request count reaches the daily cap, `acquire` raises
    `LLMQuotaExceededError` at once instead of waiting for hours. 0 disables a limit. The
    daily count is kept in memory, so a restart resets it; the provider's own 429 is the
    backstop. One limiter is shared by everything that calls the same model.
    """

    def __init__(
        self,
        *,
        requests_per_minute: int,
        tokens_per_minute: int,
        requests_per_day: int = 0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rpm = requests_per_minute
        self._tpm = tokens_per_minute
        self._rpd = requests_per_day
        self._day: deque[float] = deque()
        self._clock = clock
        self._sleep = sleep
        self._entries: deque[_Entry] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int) -> Reservation:
        """Wait for capacity, then record the request."""
        async with self._lock:
            while True:
                now = self._clock()
                self._expire(now)
                if self._rpd and len(self._day) >= self._rpd:
                    raise LLMQuotaExceededError(details={"requests_per_day": self._rpd})
                wait = self._wait_seconds(now, estimated_tokens)
                if wait <= 0:
                    entry = _Entry(now, max(estimated_tokens, 0))
                    self._entries.append(entry)
                    self._day.append(now)
                    return Reservation(entry)
                await self._sleep(wait)

    def _expire(self, now: float) -> None:
        while self._entries and now - self._entries[0].at >= WINDOW_SECONDS:
            self._entries.popleft()
        while self._day and now - self._day[0] >= DAY_SECONDS:
            self._day.popleft()

    def _wait_seconds(self, now: float, tokens: int) -> float:
        if not self._entries:
            return 0.0
        waits = [0.0]
        if self._rpm and len(self._entries) >= self._rpm:
            waits.append(self._entries[len(self._entries) - self._rpm].at + WINDOW_SECONDS - now)
        if self._tpm:
            used = sum(entry.tokens for entry in self._entries)
            # Drop the oldest entries until the new request fits.
            for entry in self._entries:
                if used + tokens <= self._tpm:
                    break
                used -= entry.tokens
                waits.append(entry.at + WINDOW_SECONDS - now)
        return max(waits)
