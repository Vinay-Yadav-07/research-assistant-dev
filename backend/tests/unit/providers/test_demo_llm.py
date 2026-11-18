import os

import pytest
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.providers.factory import build_providers
from app.providers.fakes.demo_llm import DEMO_MARKER, DemoLLM, register_demo_reply
from app.providers.llm import ChatMessage
from app.providers.tracing import configure_tracing
from app.providers.usage import track_usage

MESSAGES = [ChatMessage(role="user", content="What is a hydrogel?")]


class DemoOnly(BaseModel):
    note: str


class Unregistered(BaseModel):
    note: str


async def test_text_is_visibly_marked_and_counted() -> None:
    llm = DemoLLM(model_name="demo-llm-fast")

    with track_usage() as usage:
        result = await llm.generate_text(MESSAGES)

    assert result.output.startswith(DEMO_MARKER)
    assert result.model == "demo-llm-fast"
    assert usage.calls == 1


async def test_structured_uses_the_registered_reply() -> None:
    register_demo_reply(DemoOnly, lambda messages: {"note": f"{DEMO_MARKER} {len(messages)}"})

    result = await DemoLLM(model_name="demo").generate_structured(MESSAGES, DemoOnly)

    assert result.output == DemoOnly(note=f"{DEMO_MARKER} 1")


async def test_unregistered_schema_explains_how_to_fix_it() -> None:
    with pytest.raises(ProviderConfigurationError, match="Unregistered"):
        await DemoLLM(model_name="demo").generate_structured(MESSAGES, Unregistered)


def test_demo_tiers_build_for_local_runs(settings: Settings) -> None:
    providers = build_providers(
        settings.model_copy(update={"llm_fast_provider": "demo", "llm_strong_provider": "demo"})
    )

    assert isinstance(providers.llm_fast, DemoLLM)
    assert providers.llm_strong.model_name == "demo-llm-strong"


@pytest.mark.parametrize("variable", ["LLM_FAST_PROVIDER", "LLM_STRONG_PROVIDER"])
def test_demo_is_refused_in_prod(clean_env: pytest.MonkeyPatch, variable: str) -> None:
    clean_env.setenv(variable, "demo")

    with pytest.raises(ValidationError, match="demo LLM provider is not allowed"):
        Settings(
            _env_file=None,
            environment="prod",
            supabase_url="https://x.supabase.co",
            supabase_secret_key="sb_secret_x",
        )


def test_tracing_requires_a_key(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LANGSMITH_TRACING", "true")

    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY"):
        Settings(_env_file=None)


def test_configure_tracing_sets_and_clears_the_environment(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("LANGSMITH_TRACING", "true")
    clean_env.setenv("LANGSMITH_API_KEY", "lsv2_test")
    enabled = Settings(_env_file=None)

    configure_tracing(enabled)
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "research-assistant"

    configure_tracing(Settings(_env_file=None, langsmith_tracing=False, langsmith_api_key=None))
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LANGSMITH_API_KEY" not in os.environ
