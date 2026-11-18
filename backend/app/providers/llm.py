"""LLM provider interface and the shared structured-output validation used by every provider."""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import LLMOutputError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
OutputT = TypeVar("OutputT")
ModelTier = Literal["fast", "strong"]


class ChatMessage(BaseModel):
    """One message in a chat prompt. Kept independent of any LLM library."""

    role: Literal["system", "user", "assistant"]
    content: str


class TokenUsage(BaseModel):
    """Token counts for one LLM call (feeds `agent_runs` and the LLM-call budget)."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class LLMResult(BaseModel, Generic[OutputT]):
    """The output of one LLM call plus the model that produced it and its token usage."""

    output: OutputT
    model: str
    usage: TokenUsage


class LLMProvider(Protocol):
    """A chat model bound to one model ID. Agents receive an instance; they never pick models."""

    @property
    def model_name(self) -> str: ...

    async def generate_text(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[str]:
        """Return free text. Used only where no structure is needed (e.g. eval baselines)."""
        ...

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[T]:
        """Return a validated instance of `schema`, or raise `LLMOutputError`."""
        ...


def parse_structured(schema: type[T], raw: str | Mapping[str, Any] | BaseModel) -> T:
    """Validate raw model output against `schema`.

    Every provider (real and fake) routes its output through this function, so agents see one
    validation behaviour. Validation errors become `LLMOutputError`; the raw output is logged,
    never returned to callers.
    """
    try:
        if isinstance(raw, schema):
            return raw
        if isinstance(raw, BaseModel):
            return schema.model_validate(raw.model_dump())
        if isinstance(raw, str):
            return schema.model_validate_json(raw)
        return schema.model_validate(dict(raw))
    except ValidationError as exc:
        logger.warning("LLM output failed %s validation: %.500s", schema.__name__, _preview(raw))
        raise LLMOutputError(
            details={
                "schema": schema.__name__,
                "errors": exc.errors(include_url=False, include_context=False, include_input=False),
            }
        ) from exc


def _preview(raw: str | Mapping[str, Any] | BaseModel) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, BaseModel):
        return raw.model_dump_json()
    return json.dumps(raw, default=str)
