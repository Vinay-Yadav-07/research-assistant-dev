import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from tests.conftest import CONFIG_ENV_VARS


def load(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_need_no_keys_or_database(clean_env: pytest.MonkeyPatch) -> None:
    settings = load()

    assert settings.environment == "local"
    assert settings.database_url is None
    assert settings.cors_origins == []
    providers = [
        settings.llm_fast_provider,
        settings.llm_strong_provider,
        settings.embedding_provider,
        settings.reranker_provider,
        settings.nli_provider,
        settings.parser_provider,
        settings.search_provider,
        settings.web_search_provider,
    ]
    assert providers == ["fake"] * 8
    assert settings.embedding_dimension == 384


def test_local_model_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = load()

    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.reranker_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert settings.nli_model == "cross-encoder/nli-deberta-v3-xsmall"
    assert settings.preload_models is False
    assert settings.local_inference_concurrency == 1
    assert settings.rerank_candidates == 20
    assert settings.reranker_max_length == 512
    assert settings.run_benchmark_on_startup is False


@pytest.mark.parametrize(
    "variable",
    ["LOCAL_INFERENCE_CONCURRENCY", "RERANK_CANDIDATES", "RERANKER_MAX_LENGTH", "NLI_MAX_LENGTH"],
)
def test_local_model_limits_must_be_positive(clean_env: pytest.MonkeyPatch, variable: str) -> None:
    clean_env.setenv(variable, "0")

    with pytest.raises(ValidationError):
        load()


def test_environment_variables_override_defaults(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ENVIRONMENT", "prod")
    clean_env.setenv("SUPABASE_URL", "https://project.supabase.co")
    clean_env.setenv("SUPABASE_SECRET_KEY", "sb_secret_x")
    clean_env.setenv("LOG_LEVEL", "DEBUG")
    clean_env.setenv("LOG_JSON", "true")
    clean_env.setenv("LLM_FAST_PROVIDER", "groq")
    clean_env.setenv("LLM_FAST_MODEL", "some-fast-model")
    clean_env.setenv("LLM_STRONG_PROVIDER", "gemini")
    clean_env.setenv("WEB_SEARCH_PROVIDER", "tavily")
    clean_env.setenv("PARSER_PROVIDER", "pymupdf4llm")
    clean_env.setenv("READINESS_TIMEOUT_SECONDS", "2.5")

    settings = load()

    assert settings.environment == "prod"
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True
    assert settings.llm_fast_provider == "groq"
    assert settings.llm_fast_model == "some-fast-model"
    assert settings.llm_strong_provider == "gemini"
    assert settings.web_search_provider == "tavily"
    assert settings.parser_provider == "pymupdf4llm"
    assert settings.readiness_timeout_seconds == 2.5


def test_unit_tests_ignore_a_dotenv_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("ENVIRONMENT=prod\nSUPABASE_URL=https://x.supabase.co\n")
    monkeypatch.chdir(tmp_path)

    assert Settings().environment == "local"
    assert get_settings().supabase_url is None


def test_unit_tests_ignore_config_variables_from_the_shell() -> None:
    assert not any(name in os.environ for name in CONFIG_ENV_VARS)


def test_env_file_is_loaded(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ENVIRONMENT=dev\nCORS_ORIGINS=https://a.example\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.environment == "dev"
    assert settings.cors_origins == ["https://a.example"]


@pytest.mark.parametrize(
    "raw",
    [
        "https://a.example, https://b.example",
        '["https://a.example", "https://b.example"]',
    ],
)
def test_cors_origins_accept_comma_separated_or_json(
    clean_env: pytest.MonkeyPatch, raw: str
) -> None:
    clean_env.setenv("CORS_ORIGINS", raw)

    assert load().cors_origins == ["https://a.example", "https://b.example"]


def test_empty_cors_origins_is_empty_list(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CORS_ORIGINS", "")

    assert load().cors_origins == []


@pytest.mark.parametrize(
    "variable", ["LLM_FAST_PROVIDER", "LLM_STRONG_PROVIDER", "WEB_SEARCH_PROVIDER"]
)
def test_invalid_provider_is_rejected(clean_env: pytest.MonkeyPatch, variable: str) -> None:
    clean_env.setenv(variable, "not-a-provider")

    with pytest.raises(ValidationError):
        load()


def test_embedding_dimension_must_be_positive(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("EMBEDDING_DIMENSION", "0")

    with pytest.raises(ValidationError):
        load()


def test_empty_database_url_means_not_configured(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "")

    assert load().database_url is None


def test_database_url_is_secret(clean_env: pytest.MonkeyPatch) -> None:
    url = "postgresql+psycopg://user:hunter2@db.example:5432/postgres"
    clean_env.setenv("DATABASE_URL", url)

    settings = load()

    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == url
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.model_dump())


def test_get_settings_is_cached(clean_env: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_prod_requires_supabase_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ENVIRONMENT", "prod")

    with pytest.raises(ValidationError, match="SUPABASE_URL is required"):
        load()


def test_prod_requires_supabase_secret_key(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ENVIRONMENT", "prod")
    clean_env.setenv("SUPABASE_URL", "https://project.supabase.co")
    clean_env.setenv("SUPABASE_SECRET_KEY", " ")

    with pytest.raises(ValidationError, match="SUPABASE_SECRET_KEY is required"):
        load()


def test_storage_and_ingestion_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = load()

    assert settings.supabase_secret_key is None
    assert settings.storage_bucket == "documents"
    assert settings.max_upload_bytes == 25 * 1024 * 1024
    assert settings.ingestion_concurrency == 1
    assert settings.ingestion_stale_minutes == 15


@pytest.mark.parametrize("environment", ["local", "test", "dev"])
def test_non_prod_runs_without_supabase_url(
    clean_env: pytest.MonkeyPatch, environment: str
) -> None:
    clean_env.setenv("ENVIRONMENT", environment)
    clean_env.setenv("SUPABASE_URL", "")

    settings = load()

    assert settings.supabase_url is None
    assert settings.jwt_issuer is None
    assert settings.jwks_url is None


def test_auth_urls_derive_from_supabase_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SUPABASE_URL", "https://abc.supabase.co/")

    settings = load()

    assert settings.jwt_issuer == "https://abc.supabase.co/auth/v1"
    assert settings.jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"
    assert settings.jwt_audience == "authenticated"
    assert settings.jwt_leeway_seconds == 30


def test_jwks_url_can_be_overridden(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SUPABASE_URL", "https://abc.supabase.co")
    clean_env.setenv("SUPABASE_JWKS_URL", "https://keys.example.com/jwks.json")

    assert load().jwks_url == "https://keys.example.com/jwks.json"


def test_string_settings_are_stripped(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ENVIRONMENT", " dev\r")
    clean_env.setenv("EMBEDDING_PROVIDER", "fake ")
    clean_env.setenv("EMBEDDING_MODEL", "  BAAI/bge-small-en-v1.5\t")
    clean_env.setenv("DATABASE_URL", " postgresql+psycopg://u:p@host:5432/db \n")
    clean_env.setenv("SUPABASE_URL", " https://abc.supabase.co ")
    clean_env.setenv("CORS_ORIGINS", " http://localhost:3000 , https://app.example.com ")

    settings = load()

    assert settings.environment == "dev"
    assert settings.embedding_provider == "fake"
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@host:5432/db"
    assert settings.supabase_url == "https://abc.supabase.co"
    assert settings.cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_whitespace_only_database_url_is_not_configured(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "   ")

    assert load().database_url is None


def test_stripping_applies_to_init_arguments(clean_env: pytest.MonkeyPatch) -> None:
    assert load(embedding_query_prefix="  query: ").embedding_query_prefix == "query:"


def test_chunk_min_must_not_exceed_max(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHUNK_MIN_TOKENS", "500")

    with pytest.raises(ValidationError, match="CHUNK_MIN_TOKENS"):
        load()


def test_parser_and_chunking_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = load()

    assert settings.pdf_min_text_chars_per_page == 100
    assert (settings.chunk_min_tokens, settings.chunk_max_tokens) == (350, 450)
    assert settings.chunk_overlap_ratio == 0.12
    assert settings.chunk_merge_below_tokens == 80
    assert settings.chunk_hard_max_tokens == 510
    assert settings.boilerplate_max_line_chars == 200


def test_chunk_max_must_not_exceed_hard_max(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHUNK_MAX_TOKENS", "520")

    with pytest.raises(ValidationError, match="CHUNK_HARD_MAX_TOKENS"):
        load()


def test_verification_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = load()

    assert (settings.verification_supported_score, settings.verification_unsupported_score) == (
        0.9,
        0.0,
    )
    assert settings.verification_min_claims == 1


def test_verification_bands_must_not_overlap(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("VERIFICATION_SUPPORTED_SCORE", "0.2")
    clean_env.setenv("VERIFICATION_UNSUPPORTED_SCORE", "0.3")

    with pytest.raises(ValidationError, match="VERIFICATION_UNSUPPORTED_SCORE"):
        load()


def test_live_search_requires_contact_email(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SEARCH_PROVIDER", "live")
    clean_env.setenv("CONTACT_EMAIL", "  ")

    with pytest.raises(ValidationError, match="CONTACT_EMAIL is required"):
        load()


def test_live_search_with_contact_email(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SEARCH_PROVIDER", "live")
    clean_env.setenv("CONTACT_EMAIL", " team@example.org ")

    settings = load()

    assert settings.contact_email == "team@example.org"
    assert settings.scholarly_timeout_seconds == 5.0
    assert settings.doi_max_candidates == 3
