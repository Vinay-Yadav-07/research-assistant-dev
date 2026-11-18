"""Hosted chat models (Groq, Gemini) behind `LLMProvider`, via LangChain integrations.

The LangChain clients' own retries are switched off: this module retries (SRS §20), so rate
limiting and usage counting see every attempt the same way for every provider.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.errors import LLMOutputError, LLMProviderError, LLMQuotaExceededError
from app.providers.llm import ChatMessage, LLMProvider, LLMResult, TokenUsage, parse_structured
from app.providers.rate_limit import RateLimiter
from app.providers.usage import record_call, record_failed_attempt

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Rough token estimate for rate limiting before the provider reports real usage.
_CHARS_PER_TOKEN = 4
_DEFAULT_OUTPUT_ESTIMATE = 1024


def is_retryable(exc: BaseException) -> bool:
    """Rate limits, server errors, timeouts, and connection failures are worth retrying.

    LangChain integrations re-raise SDK errors `from` the original, so the whole cause chain is
    checked. Groq errors carry `status_code`; google-genai errors carry an integer `code`.
    """
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, TimeoutError | httpx.TransportError):
            return True
        if type(current).__name__ in {"APIConnectionError", "APITimeoutError"}:
            return True
        status = getattr(current, "status_code", None)
        if not isinstance(status, int):
            status = getattr(current, "code", None)
        if isinstance(status, int) and (status == 429 or status >= 500):
            return True
        current = current.__cause__
    return False


def is_daily_quota(exc: BaseException) -> bool:
    """A 429 for a per-day quota (Gemini "...PerDay..." quota IDs, Groq "requests per day").

    Retrying cannot succeed until the quota resets, so these fail at once.
    """
    current: BaseException | None = exc
    while current is not None:
        text = str(current).lower()
        rate_limited = 429 in (
            getattr(current, "status_code", None),
            getattr(current, "code", None),
        )
        if (rate_limited or "429" in text) and ("perday" in text or "per day" in text):
            return True
        current = current.__cause__
    return False


def is_schema_rejection(exc: BaseException) -> bool:
    """A 400 in which the provider refused its own reply for not matching the JSON schema
    (Groq's best-effort `json_schema`: "Generated JSON does not match the expected schema")."""
    current: BaseException | None = exc
    while current is not None:
        text = str(current).lower()
        if getattr(current, "status_code", None) == 400 and (
            "json_validate_failed" in text or "does not match the expected schema" in text
        ):
            return True
        current = current.__cause__
    return False


class LangChainLLM(LLMProvider):
    """One hosted model. `temperature_field`/`max_tokens_field` name the chat model's fields."""

    def __init__(
        self,
        chat_model: BaseChatModel,
        *,
        model_name: str,
        provider: str,
        limiter: RateLimiter,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        temperature_field: str = "temperature",
        max_tokens_field: str = "max_tokens",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        schema_rejections_are_output_errors: bool = False,
    ) -> None:
        """`schema_rejections_are_output_errors` (the graph tier only, D-084) reports a provider
        refusing its reply for the schema as `LLMOutputError`, like an invalid reply."""
        self._schema_rejections = schema_rejections_are_output_errors
        self._chat_model = chat_model
        self._model_name = model_name
        self._provider = provider
        self._limiter = limiter
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_base = retry_base_seconds
        self._temperature_field = temperature_field
        self._max_tokens_field = max_tokens_field
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"LangChainLLM(provider={self._provider!r}, model={self._model_name!r})"

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
        model = self._configured(temperature, max_output_tokens)
        reply = await self._call(
            lambda: model.ainvoke(_to_langchain(messages)), messages, max_output_tokens
        )
        message = _ai_message(reply)
        text = str(message.text)
        return LLMResult[str](output=text, model=self._model_name, usage=_usage(message))

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResult[T]:
        runnable = self._configured(temperature, max_output_tokens).with_structured_output(
            schema, method="json_schema", include_raw=True
        )
        reply = await self._call(
            lambda: runnable.ainvoke(_to_langchain(messages)), messages, max_output_tokens
        )
        if not isinstance(reply, dict):
            raise LLMProviderError(details={"provider": self._provider})
        message = _ai_message(reply.get("raw"))
        # Validate the raw JSON ourselves so every provider fails the same way.
        output = parse_structured(schema, str(message.text))
        return LLMResult[T](output=output, model=self._model_name, usage=_usage(message))

    def _configured(self, temperature: float | None, max_output_tokens: int | None) -> Any:
        update: dict[str, Any] = {}
        if temperature is not None:
            update[self._temperature_field] = temperature
        if max_output_tokens is not None:
            update[self._max_tokens_field] = max_output_tokens
        return self._chat_model.model_copy(update=update) if update else self._chat_model

    async def _call(
        self,
        invoke: Callable[[], Awaitable[Any]],
        messages: Sequence[ChatMessage],
        max_output_tokens: int | None,
    ) -> Any:
        estimate = sum(len(m.content) for m in messages) // _CHARS_PER_TOKEN + (
            max_output_tokens or _DEFAULT_OUTPUT_ESTIMATE
        )
        for attempt in range(self._max_retries + 1):
            reservation = await self._limiter.acquire(estimate)
            try:
                reply = await asyncio.wait_for(invoke(), timeout=self._timeout)
            except Exception as exc:
                record_failed_attempt()
                if self._schema_rejections and is_schema_rejection(exc):
                    raise LLMOutputError(
                        details={"errors": [{"loc": (), "type": "provider_schema_rejected"}]}
                    ) from exc
                if is_daily_quota(exc):
                    logger.warning(
                        "%s daily quota for %s is used up", self._provider, self._model_name
                    )
                    raise LLMQuotaExceededError(
                        details={"provider": self._provider, "model": self._model_name}
                    ) from exc
                retryable = is_retryable(exc)
                # Log the type only: SDK messages can echo request details.
                logger.warning(
                    "%s call to %s failed (attempt %d/%d, %s%s)",
                    self._provider,
                    self._model_name,
                    attempt + 1,
                    self._max_retries + 1,
                    type(exc).__name__,
                    ", retrying" if retryable and attempt < self._max_retries else "",
                )
                if not retryable or attempt == self._max_retries:
                    raise LLMProviderError(
                        details={"provider": self._provider, "model": self._model_name}
                    ) from exc
                await self._sleep(self._retry_base * 2**attempt)
                continue
            message = _ai_message(reply.get("raw") if isinstance(reply, dict) else reply)
            usage = _usage(message)
            reservation.settle(usage.input_tokens + usage.output_tokens)
            record_call(self._model_name, usage)
            return reply
        raise AssertionError("unreachable")


def _to_langchain(messages: Sequence[ChatMessage]) -> list[AnyMessage]:
    converted: list[AnyMessage] = []
    for message in messages:
        match message.role:
            case "system":
                converted.append(SystemMessage(message.content))
            case "user":
                converted.append(HumanMessage(message.content))
            case "assistant":
                converted.append(AIMessage(message.content))
    return converted


def _ai_message(value: object) -> AIMessage:
    if not isinstance(value, AIMessage):
        raise LLMProviderError("The language model returned no message.")
    return value


def _usage(message: AIMessage) -> TokenUsage:
    metadata = message.usage_metadata
    if metadata is None:
        return TokenUsage(input_tokens=0, output_tokens=0)
    return TokenUsage(
        input_tokens=metadata["input_tokens"], output_tokens=metadata["output_tokens"]
    )
