import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.deps import get_providers
from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.main import create_app
from app.providers.factory import Providers, build_llm, build_providers
from app.providers.fakes import (
    FakeEmbedder,
    FakeLLM,
    FakeNLI,
    FakeParser,
    FakeReranker,
    FakeScholarlySearch,
    FakeWebSearch,
)


def test_defaults_build_all_fakes(settings: Settings) -> None:
    providers = build_providers(settings)

    assert isinstance(providers.llm_fast, FakeLLM)
    assert isinstance(providers.llm_strong, FakeLLM)
    assert isinstance(providers.embedder, FakeEmbedder)
    assert isinstance(providers.reranker, FakeReranker)
    assert isinstance(providers.nli, FakeNLI)
    assert isinstance(providers.parser, FakeParser)
    assert isinstance(providers.scholarly_search, FakeScholarlySearch)
    assert isinstance(providers.web_search, FakeWebSearch)


def test_llm_tiers_are_separate_instances(settings: Settings) -> None:
    fast = build_llm(settings, "fast")
    strong = build_llm(settings, "strong")

    assert fast is not strong
    assert fast.model_name == "fake-llm-fast"
    assert strong.model_name == "fake-llm-strong"


def test_embedder_uses_configured_dimension(settings: Settings) -> None:
    providers = build_providers(settings.model_copy(update={"embedding_dimension": 32}))

    assert providers.embedder.dimension == 32


@pytest.mark.parametrize(
    ("field", "value", "phase"),
    [
        ("parser_provider", "docling", 1),
        ("web_search_provider", "tavily", 5),
    ],
)
def test_unimplemented_providers_fail_with_a_clear_error(
    settings: Settings, field: str, value: str, phase: int
) -> None:
    configured = settings.model_copy(update={field: value})

    with pytest.raises(ProviderConfigurationError, match=f"'{value}'.*Phase {phase}"):
        build_providers(configured)


def test_live_scholarly_search_is_built_with_contact_email(settings: Settings) -> None:
    from app.providers.live.scholarly import LiveScholarlySearch

    configured = settings.model_copy(
        update={"search_provider": "live", "contact_email": "team@example.org"}
    )

    assert isinstance(build_providers(configured).scholarly_search, LiveScholarlySearch)


def test_app_exposes_providers_after_startup(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(app.state.providers, Providers)


def test_get_providers_returns_the_startup_instance(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app):
        request = Request({"type": "http", "app": app})

        assert get_providers(request) is app.state.providers


def test_app_startup_fails_with_an_unimplemented_provider(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"llm_fast_provider": "groq"}))

    with pytest.raises(ProviderConfigurationError), TestClient(app):
        pass
