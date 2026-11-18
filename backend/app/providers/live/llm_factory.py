"""Builds the Groq and Gemini chat models from settings (imported only when selected)."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.providers.live.llm import LangChainLLM
from app.providers.llm import ModelTier
from app.providers.rate_limit import RateLimiter


def build_hosted_llm(
    settings: Settings,
    provider: Literal["groq", "gemini"],
    model: str,
    tier: ModelTier | Literal["graph"],
    limiter: RateLimiter,
    *,
    api_key: SecretStr | None = None,
    schema_rejections_are_output_errors: bool = False,
    max_retries: int | None = None,
    retry_base_seconds: float | None = None,
) -> LangChainLLM:
    """A hosted chat model for one tier. Keys come only from settings and are never logged.

    `api_key` replaces the provider's key (the graph tier's own key, D-083); `max_retries` and
    `retry_base_seconds` replace the shared retry settings (the graph tier's own, D-085).
    """
    if not model:
        raise ProviderConfigurationError(
            f"LLM_{tier.upper()}_MODEL must be set for provider '{provider}'.",
            details={"provider": provider, "tier": tier},
        )
    key = api_key or (settings.groq_api_key if provider == "groq" else settings.gemini_api_key)
    if key is None:
        raise ProviderConfigurationError(
            f"{provider.upper()}_API_KEY is required when an LLM tier uses '{provider}'.",
            details={"provider": provider, "tier": tier},
        )
    chat_model: BaseChatModel
    if provider == "groq":
        from langchain_groq import ChatGroq

        chat_model = ChatGroq(
            model_name=model,
            groq_api_key=key,
            max_retries=0,
            request_timeout=settings.llm_timeout_seconds,
        )
        max_tokens_field = "max_tokens"
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI

        chat_model = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=key,
            max_retries=0,
            timeout=settings.llm_timeout_seconds,
        )
        max_tokens_field = "max_output_tokens"
    return LangChainLLM(
        chat_model,
        model_name=model,
        provider=provider,
        limiter=limiter,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries if max_retries is None else max_retries,
        retry_base_seconds=(
            settings.llm_retry_base_seconds if retry_base_seconds is None else retry_base_seconds
        ),
        max_tokens_field=max_tokens_field,
        schema_rejections_are_output_errors=schema_rejections_are_output_errors,
    )
