"""Deterministic, network-free provider implementations used by tests, CI, and local runs."""

from app.providers.fakes.embedding import FakeEmbedder
from app.providers.fakes.llm import FakeLLM, FakeLLMCall, FakeLLMNotScriptedError
from app.providers.fakes.nli import FakeNLI
from app.providers.fakes.parser import FakeParser
from app.providers.fakes.reranker import FakeReranker
from app.providers.fakes.search import (
    FakePdfFetcher,
    FakeScholarlySearch,
    FakeWebSearch,
    SearchCall,
)

__all__ = [
    "FakeEmbedder",
    "FakeLLM",
    "FakeLLMCall",
    "FakeLLMNotScriptedError",
    "FakeNLI",
    "FakeParser",
    "FakePdfFetcher",
    "FakeReranker",
    "FakeScholarlySearch",
    "FakeWebSearch",
    "SearchCall",
]
