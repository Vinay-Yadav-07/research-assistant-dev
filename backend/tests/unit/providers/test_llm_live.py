"""`LangChainLLM` against a stub chat model: no network, no keys."""

import logging
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import (
    LLMOutputError,
    LLMProviderError,
    LLMQuotaExceededError,
    ProviderConfigurationError,
)
from app.providers.factory import build_llm, build_providers
from app.providers.live.llm import (
    LangChainLLM,
    is_daily_quota,
    is_retryable,
    is_schema_rejection,
)
from app.providers.llm import ChatMessage
from app.providers.rate_limit import RateLimiter
from app.providers.usage import track_usage

MESSAGES = [
    ChatMessage(role="system", content="Answer briefly."),
    ChatMessage(role="user", content="What is a scaffold?"),
]


class Answer(BaseModel):
    text: str


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class StubChat(BaseChatModel):
    """Replies (AIMessage or exception) from a shared queue; records the inputs it saw."""

    replies: list[Any]
    seen: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(
            {
                "types": [m.type for m in messages],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        )
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def with_structured_output(  # type: ignore[override]
        self, schema: Any, *, method: str = "", include_raw: bool = False, **kwargs: Any
    ) -> Runnable[Any, Any]:
        """Like the real integrations with include_raw: the raw message plus a parse attempt."""
        assert method == "json_schema" and include_raw

        async def call(messages: Any) -> dict[str, Any]:
            return {"raw": await self.ainvoke(messages), "parsed": None, "parsing_error": None}

        return RunnableLambda(call)


def message(content: str, input_tokens: int = 11, output_tokens: int = 5) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def make_llm(
    replies: Sequence[Any], **overrides: Any
) -> tuple[LangChainLLM, StubChat, list[float]]:
    chat = StubChat(replies=list(replies), seen=[])
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    options: dict[str, Any] = {
        "model_name": "stub-model",
        "provider": "stub",
        "limiter": RateLimiter(requests_per_minute=0, tokens_per_minute=0),
        "timeout_seconds": 5.0,
        "max_retries": 2,
        "retry_base_seconds": 1.0,
        "sleep": sleep,
    }
    options.update(overrides)
    return LangChainLLM(chat, **options), chat, sleeps


async def test_text_reply_has_model_usage_and_converted_roles() -> None:
    llm, chat, _ = make_llm([message("A porous support.")])

    result = await llm.generate_text(MESSAGES, temperature=0.2, max_output_tokens=50)

    assert result.output == "A porous support."
    assert result.model == "stub-model"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 5)
    assert chat.seen == [{"types": ["system", "human"], "temperature": 0.2, "max_tokens": 50}]


async def test_per_call_options_do_not_change_the_shared_model() -> None:
    llm, chat, _ = make_llm([message("a"), message("b")])

    await llm.generate_text(MESSAGES, temperature=0.9)
    await llm.generate_text(MESSAGES)

    assert [seen["temperature"] for seen in chat.seen] == [0.9, None]


async def test_structured_reply_is_validated_from_the_raw_json() -> None:
    llm, _, _ = make_llm([message('{"text": "ok"}')])

    result = await llm.generate_structured(MESSAGES, Answer)

    assert result.output == Answer(text="ok")
    assert result.usage.output_tokens == 5


async def test_invalid_structured_reply_raises_llm_output_error() -> None:
    llm, _, _ = make_llm([message('{"wrong": 1}')])

    with pytest.raises(LLMOutputError):
        await llm.generate_structured(MESSAGES, Answer)


@pytest.mark.parametrize(
    "error", [StatusError(429), StatusError(503), httpx.ConnectError("down"), TimeoutError()]
)
async def test_transient_errors_are_retried_with_backoff(error: Exception) -> None:
    llm, _, sleeps = make_llm([error, error, message("finally")])

    with track_usage() as usage:
        result = await llm.generate_text(MESSAGES)

    assert result.output == "finally"
    assert sleeps == [1.0, 2.0]
    assert (usage.calls, usage.failed_attempts) == (1, 2)


async def test_gives_up_after_max_retries() -> None:
    llm, chat, sleeps = make_llm([StatusError(429)] * 3)

    with pytest.raises(LLMProviderError) as caught:
        await llm.generate_text(MESSAGES)

    assert len(chat.seen) == 3
    assert sleeps == [1.0, 2.0]
    assert caught.value.details == {"provider": "stub", "model": "stub-model"}


async def test_client_errors_are_not_retried() -> None:
    llm, chat, sleeps = make_llm([StatusError(401)])

    with pytest.raises(LLMProviderError):
        await llm.generate_text(MESSAGES)

    assert len(chat.seen) == 1
    assert sleeps == []


async def test_every_attempt_goes_through_the_rate_limiter() -> None:
    acquired: list[int] = []

    class CountingLimiter(RateLimiter):
        async def acquire(self, estimated_tokens: int):  # type: ignore[no-untyped-def]
            acquired.append(estimated_tokens)
            return await super().acquire(estimated_tokens)

    limiter = CountingLimiter(requests_per_minute=0, tokens_per_minute=0)
    llm, _, _ = make_llm([StatusError(500), message("ok")], limiter=limiter)

    await llm.generate_text(MESSAGES, max_output_tokens=100)

    assert len(acquired) == 2
    assert acquired[0] > 100


def test_retryable_status_is_found_in_the_cause_chain() -> None:
    wrapped = RuntimeError("langchain wrapper")
    wrapped.__cause__ = StatusError(503)

    class GenaiStyle(Exception):
        code = 429

    assert is_retryable(wrapped)
    assert is_retryable(GenaiStyle())
    assert not is_retryable(ValueError("bad request"))
    assert not is_retryable(StatusError(400))


# --- factory and secrets ---


def hosted(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(
        update={
            "llm_fast_provider": "groq",
            "llm_strong_provider": "gemini",
            "groq_api_key": SecretStr("gsk_test_secret_value"),
            "gemini_api_key": SecretStr("gemini_test_secret_value"),
            **update,
        }
    )


@pytest.mark.parametrize(
    ("tier", "missing", "variable"),
    [("fast", "groq_api_key", "GROQ_API_KEY"), ("strong", "gemini_api_key", "GEMINI_API_KEY")],
)
def test_key_is_required_for_the_selected_provider(
    settings: Settings, tier: Any, missing: str, variable: str
) -> None:
    with pytest.raises(ProviderConfigurationError, match=variable):
        build_llm(hosted(settings, **{missing: None}), tier)


def test_model_is_required_for_a_hosted_provider(settings: Settings) -> None:
    with pytest.raises(ProviderConfigurationError, match="LLM_FAST_MODEL"):
        build_llm(hosted(settings, llm_fast_model=""), "fast")


def test_hosted_tiers_use_the_configured_models_and_hide_keys(settings: Settings) -> None:
    configured = hosted(settings)
    providers = build_providers(configured)

    assert providers.llm_fast.model_name == configured.llm_fast_model
    assert providers.llm_strong.model_name == configured.llm_strong_model
    for text in (repr(configured), repr(providers), str(configured.model_dump())):
        assert "gsk_test_secret_value" not in text
        assert "gemini_test_secret_value" not in text


def test_tiers_on_the_same_model_share_one_limiter(settings: Settings) -> None:
    configured = hosted(settings, llm_strong_provider="groq", llm_strong_model="openai/gpt-oss-20b")
    providers = build_providers(configured)

    assert isinstance(providers.llm_fast, LangChainLLM)
    assert isinstance(providers.llm_strong, LangChainLLM)
    assert providers.llm_fast._limiter is providers.llm_strong._limiter


def test_different_models_on_one_provider_get_their_own_limiters(settings: Settings) -> None:
    configured = hosted(
        settings, llm_strong_provider="groq", llm_strong_model="openai/gpt-oss-120b"
    )
    providers = build_providers(configured)

    assert isinstance(providers.llm_fast, LangChainLLM)
    assert isinstance(providers.llm_strong, LangChainLLM)
    assert providers.llm_fast._limiter is not providers.llm_strong._limiter


def test_default_tier_models_and_limits(settings: Settings) -> None:
    assert settings.llm_strong_model == "gemini-3.5-flash-lite"
    assert (settings.llm_fast_rpm, settings.llm_fast_tpm, settings.llm_fast_rpd) == (30, 8000, 1000)
    assert (settings.llm_strong_rpm, settings.llm_strong_tpm, settings.llm_strong_rpd) == (
        15,
        250_000,
        500,
    )


class QuotaError(Exception):
    """Shaped like the Gemini wrapper's error for an exhausted daily quota."""

    code = 429

    def __init__(self) -> None:
        super().__init__(
            "429 RESOURCE_EXHAUSTED. Quota exceeded: "
            "generativelanguage.googleapis.com/generate_requests_per_model_per_day, "
            "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        )


async def test_daily_quota_429_fails_at_once_without_retries() -> None:
    llm, chat, sleeps = make_llm([QuotaError(), message("never")])

    with pytest.raises(LLMQuotaExceededError):
        await llm.generate_text(MESSAGES)

    assert len(chat.seen) == 1
    assert sleeps == []


async def test_local_daily_cap_refuses_before_calling_the_model() -> None:
    limiter = RateLimiter(requests_per_minute=0, tokens_per_minute=0, requests_per_day=1)
    llm, chat, _ = make_llm([message("first"), message("second")], limiter=limiter)
    await llm.generate_text(MESSAGES)

    with pytest.raises(LLMQuotaExceededError):
        await llm.generate_text(MESSAGES)

    assert len(chat.seen) == 1


def test_minute_rate_limit_429_is_not_a_daily_quota() -> None:
    assert not is_daily_quota(StatusError(429))
    assert is_daily_quota(QuotaError())


async def test_failure_logs_do_not_contain_the_key(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "gsk_test_secret_value"
    llm, _, _ = make_llm([StatusError(401)])
    caplog.set_level(logging.DEBUG)

    with pytest.raises(LLMProviderError) as caught:
        await llm.generate_text(MESSAGES)

    assert secret not in caplog.text
    assert secret not in str(caught.value.details)


def test_the_graph_tier_has_its_own_limiter_and_key(settings: Settings) -> None:
    configured = hosted(
        settings,
        llm_graph_provider="gemini",
        llm_graph_model=settings.llm_strong_model,
        llm_graph_api_key=SecretStr("graph_test_secret_value"),
    )
    providers = build_providers(configured)

    assert isinstance(providers.llm_graph, LangChainLLM)
    assert isinstance(providers.llm_strong, LangChainLLM)
    assert providers.llm_graph.model_name == providers.llm_strong.model_name
    assert providers.llm_graph._limiter is not providers.llm_strong._limiter
    assert providers.llm_graph._limiter is not providers.llm_fast._limiter
    assert "graph_test_secret_value" not in repr(providers)


def test_a_graph_model_shared_with_an_interactive_tier_needs_its_own_key(
    settings: Settings,
) -> None:
    shared = {"llm_fast_provider": "groq", "llm_graph_provider": "groq"}
    with pytest.raises(ValidationError, match="LLM_GRAPH_API_KEY"):
        Settings(_env_file=None, llm_graph_model=settings.llm_fast_model, **shared)  # type: ignore[call-arg, arg-type]
    Settings(_env_file=None, llm_graph_model="openai/gpt-oss-120b", **shared)  # type: ignore[call-arg, arg-type]
    Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_graph_model=settings.llm_fast_model,
        llm_graph_api_key=SecretStr("another-key"),
        **shared,  # type: ignore[arg-type]
    )


def test_the_graph_tier_needs_a_model_and_defaults_to_fake(settings: Settings) -> None:
    assert settings.llm_graph_provider == "fake"
    with pytest.raises(ProviderConfigurationError, match="LLM_GRAPH_MODEL"):
        build_providers(hosted(settings, llm_graph_provider="gemini", llm_graph_model=""))


class SchemaRejection(StatusError):
    """Shaped like Groq's 400 when its best-effort `json_schema` reply fails the schema."""

    def __init__(self) -> None:
        super().__init__(400)
        self.args = (
            "Error code: 400 - {'error': {'message': 'Generated JSON does not match the expected "
            "schema. Please adjust your prompt.', 'code': 'json_validate_failed'}}",
        )

    def __str__(self) -> str:
        return str(self.args[0])


async def test_graph_tier_reports_schema_rejections_as_invalid_output_without_retry() -> None:
    llm, chat, sleeps = make_llm([SchemaRejection()], schema_rejections_are_output_errors=True)

    with pytest.raises(LLMOutputError) as raised:
        await llm.generate_structured(MESSAGES, Answer)

    assert raised.value.details["errors"][0]["type"] == "provider_schema_rejected"
    assert (len(chat.seen), sleeps) == (1, [])


async def test_other_tiers_keep_treating_schema_rejections_as_provider_errors() -> None:
    llm, chat, _ = make_llm([SchemaRejection()])

    with pytest.raises(LLMProviderError):
        await llm.generate_structured(MESSAGES, Answer)
    assert len(chat.seen) == 1


def test_only_the_graph_tier_maps_schema_rejections(settings: Settings) -> None:
    providers = build_providers(
        hosted(settings, llm_graph_provider="groq", llm_graph_model="openai/gpt-oss-120b")
    )

    assert isinstance(providers.llm_graph, LangChainLLM)
    assert isinstance(providers.llm_fast, LangChainLLM)
    assert providers.llm_graph._schema_rejections
    assert not providers.llm_fast._schema_rejections
    assert not is_schema_rejection(StatusError(400))
    assert is_schema_rejection(SchemaRejection())


def test_only_the_graph_tier_backs_off_longer(settings: Settings) -> None:
    providers = build_providers(
        hosted(settings, llm_graph_provider="groq", llm_graph_model="openai/gpt-oss-120b")
    )

    assert isinstance(providers.llm_graph, LangChainLLM)
    assert isinstance(providers.llm_fast, LangChainLLM)
    assert (providers.llm_graph._max_retries, providers.llm_graph._retry_base) == (
        settings.llm_graph_max_retries,
        settings.llm_graph_retry_base_seconds,
    )
    assert (providers.llm_fast._max_retries, providers.llm_fast._retry_base) == (
        settings.llm_max_retries,
        settings.llm_retry_base_seconds,
    )
    assert settings.llm_graph_max_retries > settings.llm_max_retries


async def test_graph_backoff_waits_through_a_long_overload() -> None:
    replies = [StatusError(503)] * 4 + [message('{"text": "ok"}')]
    llm, chat, sleeps = make_llm(replies, max_retries=4, retry_base_seconds=10.0)

    await llm.generate_structured(MESSAGES, Answer)

    assert (len(chat.seen), sleeps) == (5, [10.0, 20.0, 40.0, 80.0])
