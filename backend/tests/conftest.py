"""Shared fixtures. Settings never read the developer's `.env`, so tests are hermetic."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

CONFIG_ENV_VARS = (
    "APP_NAME",
    "APP_VERSION",
    "ENVIRONMENT",
    "LOG_LEVEL",
    "LOG_JSON",
    "CORS_ORIGINS",
    "DATABASE_URL",
    "DB_CONNECT_TIMEOUT_SECONDS",
    "READINESS_TIMEOUT_SECONDS",
    "SUPABASE_URL",
    "SUPABASE_JWKS_URL",
    "JWT_AUDIENCE",
    "JWT_LEEWAY_SECONDS",
    "JWKS_CACHE_SECONDS",
    "JWKS_TIMEOUT_SECONDS",
    "SUPABASE_SECRET_KEY",
    "STORAGE_BUCKET",
    "STORAGE_TIMEOUT_SECONDS",
    "SIGNED_URL_TTL_SECONDS",
    "MAX_UPLOAD_BYTES",
    "INGESTION_CONCURRENCY",
    "INGESTION_STALE_MINUTES",
    "INGESTION_SWEEP_INTERVAL_MINUTES",
    "LLM_FAST_PROVIDER",
    "LLM_FAST_MODEL",
    "LLM_STRONG_PROVIDER",
    "LLM_STRONG_MODEL",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "LLM_RETRY_BASE_SECONDS",
    "LLM_FAST_RPM",
    "LLM_FAST_TPM",
    "LLM_FAST_RPD",
    "LLM_STRONG_RPM",
    "LLM_STRONG_TPM",
    "LLM_STRONG_RPD",
    "LLM_GRAPH_PROVIDER",
    "LLM_GRAPH_MODEL",
    "LLM_GRAPH_API_KEY",
    "LLM_GRAPH_RPM",
    "LLM_GRAPH_TPM",
    "LLM_GRAPH_RPD",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_QUERY_PREFIX",
    "EMBEDDING_BATCH_SIZE",
    "RERANKER_PROVIDER",
    "RERANKER_MODEL",
    "RERANKER_MAX_LENGTH",
    "RERANKER_BATCH_SIZE",
    "RERANK_CANDIDATES",
    "DENSE_TOP_K",
    "LEXICAL_TOP_K",
    "RRF_K",
    "RETRIEVAL_TOP_K",
    "KG_HEARTBEAT_SECONDS",
    "KG_JOB_STALE_MINUTES",
    "KG_JOB_SWEEP_INTERVAL_MINUTES",
    "KG_MAX_CALLS_PER_JOB",
    "KG_MIN_CHUNK_WORDS",
    "KG_MAX_CHUNKS_PER_PAPER",
    "KG_CHUNKS_PER_CALL",
    "KG_MAX_OUTPUT_TOKENS",
    "KG_RELATION_ENTAILMENT_SCORE",
    "KG_RELATION_CONTRADICTION_SCORE",
    "KG_GRAPH_MAX_NODES",
    "MAX_QUERY_CHARS",
    "NLI_PROVIDER",
    "NLI_MODEL",
    "NLI_MAX_LENGTH",
    "NLI_BATCH_SIZE",
    "PRELOAD_MODELS",
    "LOCAL_INFERENCE_CONCURRENCY",
    "RUN_BENCHMARK_ON_STARTUP",
    "PARSER_PROVIDER",
    "PDF_MIN_TEXT_CHARS_PER_PAGE",
    "BOILERPLATE_MIN_PAGES",
    "BOILERPLATE_MIN_PAGE_FRACTION",
    "BOILERPLATE_MAX_LINE_CHARS",
    "CHUNK_MIN_TOKENS",
    "CHUNK_MAX_TOKENS",
    "CHUNK_OVERLAP_RATIO",
    "CHUNK_MERGE_BELOW_TOKENS",
    "CHUNK_HARD_MAX_TOKENS",
    "SEARCH_PROVIDER",
    "CONTACT_EMAIL",
    "SCHOLARLY_TIMEOUT_SECONDS",
    "DOI_MAX_CANDIDATES",
    "WEB_SEARCH_PROVIDER",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every config variable from the process environment."""
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def settings(clean_env: pytest.MonkeyPatch) -> Settings:
    """Settings with no database and one allowed CORS origin."""
    return Settings(
        _env_file=None,
        environment="test",
        cors_origins=["http://localhost:3000"],
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
