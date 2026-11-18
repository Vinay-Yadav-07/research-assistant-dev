"""Per-run LLM usage counting (NFR-13: LLM calls and tokens per question).

A run opens a `track_usage()` scope; every LLM provider records each completed call into all
scopes active in the current context, so a graph run and an inner step can count separately.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, Field

from app.providers.llm import TokenUsage


class ModelUsage(BaseModel):
    """Calls and tokens for one model."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class RunUsage(BaseModel):
    """Totals for one scope, overall and per model. Failed attempts are not calls."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failed_attempts: int = 0
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


_active: ContextVar[tuple[RunUsage, ...]] = ContextVar("llm_usage_scopes", default=())


@contextmanager
def track_usage() -> Iterator[RunUsage]:
    """Count every LLM call made inside this block (including in tasks it starts)."""
    usage = RunUsage()
    token = _active.set((*_active.get(), usage))
    try:
        yield usage
    finally:
        _active.reset(token)


def record_call(model: str, usage: TokenUsage) -> None:
    """Add one completed call to every active scope."""
    for scope in _active.get():
        scope.calls += 1
        scope.input_tokens += usage.input_tokens
        scope.output_tokens += usage.output_tokens
        per_model = scope.by_model.setdefault(model, ModelUsage())
        per_model.calls += 1
        per_model.input_tokens += usage.input_tokens
        per_model.output_tokens += usage.output_tokens


def record_failed_attempt() -> None:
    """Count an attempt that raised (it is retried or surfaces as an error)."""
    for scope in _active.get():
        scope.failed_attempts += 1
