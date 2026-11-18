"""Scripted fake LLM for tests and key-free local runs."""

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from app.providers.llm import (
    ChatMessage,
    LLMProvider,
    LLMResult,
    TokenUsage,
    parse_structured,
)
from app.providers.usage import record_call

T = TypeVar("T", bound=BaseModel)

StructuredReply = BaseModel | Mapping[str, Any] | str | Exception
TextReply = str | Exception
StructuredEntry = StructuredReply | Callable[[Sequence[ChatMessage]], StructuredReply]
TextEntry = TextReply | Callable[[Sequence[ChatMessage]], TextReply]

_ECHO_CHARS = 200


class FakeLLMNotScriptedError(RuntimeError):
    """A structured call was made for a schema with no scripted reply left.

    Deliberately not an `AppError`: code that degrades gracefully on provider errors must not
    swallow it, so a test with a missing script always fails loudly.
    """


@dataclass(frozen=True)
class FakeLLMCall:
    """One recorded call, for assertions on prompts and call counts."""

    method: Literal["text", "structured"]
    messages: tuple[ChatMessage, ...]
    schema: type[BaseModel] | None
    temperature: float | None
    max_output_tokens: int | None


class FakeLLM(LLMProvider):
    """Replies from per-schema queues of scripted entries.

    A structured entry is a model instance, a dict or JSON string (validated through
    `parse_structured`, so invalid entries raise `LLMOutputError` like a real provider), an
    exception to raise, or a callable taking the messages and returning one of those.
    An unscripted structured call always raises `FakeLLMNotScriptedError`. An unscripted text
    call echoes the last user message.
    """

    def __init__(
        self,
        *,
        model_name: str = "fake-llm",
        structured: Mapping[type[BaseModel], Iterable[StructuredEntry]] | None = None,
        text: Iterable[TextEntry] | None = None,
    ) -> None:
        self._model_name = model_name
        self._structured: defaultdict[type[BaseModel], deque[StructuredEntry]] = defaultdict(deque)
        self._text: deque[TextEntry] = deque(text or ())
        self.calls: list[FakeLLMCall] = []
        for schema, entries in (structured or {}).items():
            self.script(schema, *entries)

    @property
    def model_name(self) -> str:
        return self._model_name

    def script(self, schema: type[BaseModel], *entries: StructuredEntry) -> None:
        """Queue replies for structured calls with `schema`."""
        self._structured[schema].extend(entries)

    def script_text(self, *entries: TextEntry) -> None:
        """Queue replies for text calls."""
        self._text.extend(entries)

    async def generate_text(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[str]:
        self._record("text", messages, None, temperature, max_output_tokens)
        if self._text:
            entry = self._text.popleft()
            reply = entry(messages) if callable(entry) else entry
        else:
            reply = "[fake] " + _last_user_message(messages)[:_ECHO_CHARS]
        if isinstance(reply, Exception):
            raise reply
        usage = _usage(messages, reply)
        record_call(self._model_name, usage)
        return LLMResult[str](output=reply, model=self._model_name, usage=usage)

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[T]:
        self._record("structured", messages, schema, temperature, max_output_tokens)
        queue = self._structured.get(schema)
        if not queue:
            raise FakeLLMNotScriptedError(
                f"FakeLLM has no scripted reply for {schema.__name__}; "
                f"call script({schema.__name__}, ...) first."
            )
        entry = queue.popleft()
        reply = entry(messages) if callable(entry) else entry
        if isinstance(reply, Exception):
            raise reply
        output = parse_structured(schema, reply)
        usage = _usage(messages, output.model_dump_json())
        record_call(self._model_name, usage)
        return LLMResult[T](output=output, model=self._model_name, usage=usage)

    def _record(
        self,
        method: Literal["text", "structured"],
        messages: Sequence[ChatMessage],
        schema: type[BaseModel] | None,
        temperature: float | None,
        max_output_tokens: int | None,
    ) -> None:
        self.calls.append(
            FakeLLMCall(method, tuple(messages), schema, temperature, max_output_tokens)
        )


def _last_user_message(messages: Sequence[ChatMessage]) -> str:
    return next((m.content for m in reversed(messages) if m.role == "user"), "")


def _usage(messages: Sequence[ChatMessage], output: str) -> TokenUsage:
    input_tokens = sum(len(message.content.split()) for message in messages)
    return TokenUsage(input_tokens=input_tokens, output_tokens=len(output.split()))
