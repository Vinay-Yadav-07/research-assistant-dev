"""Canned LLM for key-free local runs (`LLM_*_PROVIDER=demo`), never for tests or prod.

Unit tests use the strict `FakeLLM`. The demo provider answers each structured schema with a
reply builder that the schema's owner registers with `register_demo_reply` (later phases add
them for A1-A3). Builders must start user-visible text with `DEMO_MARKER`; free text always
does. Settings refuse this provider when ENVIRONMENT=prod (D-062).
"""

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.errors import ProviderConfigurationError
from app.providers.llm import ChatMessage, LLMProvider, LLMResult, TokenUsage, parse_structured
from app.providers.usage import record_call

T = TypeVar("T", bound=BaseModel)

DEMO_MARKER = "[DEMO OUTPUT]"

DemoReply = Callable[[Sequence[ChatMessage]], BaseModel | dict[str, Any]]

_REPLIES: dict[type[BaseModel], DemoReply] = {}


def register_demo_reply(schema: type[BaseModel], reply: DemoReply) -> None:
    """Register how the demo LLM answers structured calls for `schema`."""
    _REPLIES[schema] = reply


class DemoLLM(LLMProvider):
    """Deterministic, visibly marked replies; no network."""

    def __init__(self, *, model_name: str) -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_text(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[str]:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        output = (
            f"{DEMO_MARKER} No language model is configured; this is canned text. "
            + (last_user[:200])
        )
        return self._result(messages, output, output)

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[T]:
        reply = _REPLIES.get(schema)
        if reply is None:
            raise ProviderConfigurationError(
                f"The demo LLM has no reply for {schema.__name__}; configure a real LLM provider.",
                details={"schema": schema.__name__},
            )
        output = parse_structured(schema, reply(messages))
        return self._result(messages, output, output.model_dump_json())

    def _result(self, messages: Sequence[ChatMessage], output: Any, text: str) -> LLMResult[Any]:
        usage = TokenUsage(
            input_tokens=sum(len(m.content.split()) for m in messages),
            output_tokens=len(text.split()),
        )
        record_call(self._model_name, usage)
        return LLMResult(output=output, model=self._model_name, usage=usage)
