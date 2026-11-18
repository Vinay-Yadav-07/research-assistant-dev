"""One real call per hosted LLM provider (needs GROQ_API_KEY / GEMINI_API_KEY in backend/.env)."""

from typing import Literal

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.providers.factory import build_llm
from app.providers.llm import ChatMessage
from app.providers.usage import track_usage

pytestmark = pytest.mark.integration


class Capital(BaseModel):
    city: str


@pytest.mark.parametrize("provider", ["groq", "gemini"])
async def test_structured_call_returns_validated_output_and_usage(
    provider: Literal["groq", "gemini"],
) -> None:
    settings = Settings()
    key = settings.groq_api_key if provider == "groq" else settings.gemini_api_key
    if key is None:
        pytest.skip(f"{provider.upper()}_API_KEY not set")
    model = "openai/gpt-oss-20b" if provider == "groq" else "gemini-3.5-flash-lite"
    llm = build_llm(
        settings.model_copy(update={"llm_fast_provider": provider, "llm_fast_model": model}),
        "fast",
    )
    messages = [
        ChatMessage(role="system", content="Reply with JSON matching the schema."),
        ChatMessage(role="user", content="What is the capital of France?"),
    ]

    with track_usage() as usage:
        result = await llm.generate_structured(messages, Capital, temperature=0)

    assert "paris" in result.output.city.lower()
    assert result.usage.input_tokens > 0
    assert usage.calls == 1
