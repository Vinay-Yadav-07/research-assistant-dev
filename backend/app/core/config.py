"""Application settings loaded from environment variables and an optional `.env` file."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "dev", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LLMProviderName = Literal["fake", "demo", "groq", "gemini"]
# The graph tier never uses canned demo replies: they could not pass evidence validation.
GraphLLMProviderName = Literal["fake", "groq", "gemini"]
EmbeddingProviderName = Literal["fake", "sentence_transformers"]
RerankerProviderName = Literal["fake", "cross_encoder"]
NLIProviderName = Literal["fake", "cross_encoder"]
ParserProviderName = Literal["fake", "pymupdf4llm", "docling"]
SearchProviderName = Literal["fake", "live"]
WebSearchProviderName = Literal["fake", "tavily"]


class Settings(BaseSettings):
    """All runtime configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Research Assistant API"
    app_version: str = "0.1.0"
    environment: Environment = "local"

    log_level: LogLevel = "INFO"
    log_json: bool = False

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    database_url: SecretStr | None = None
    db_connect_timeout_seconds: int = Field(default=3, gt=0)
    readiness_timeout_seconds: float = Field(default=5.0, gt=0)

    # Supabase Auth (FR-01). Without SUPABASE_URL, authenticated endpoints return 503;
    # in prod the app refuses to start.
    supabase_url: str | None = None
    # Defaults to `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`.
    supabase_jwks_url: str | None = None
    jwt_audience: str = "authenticated"
    # Clock skew allowed on `exp` and `nbf`.
    jwt_leeway_seconds: int = Field(default=30, ge=0)
    jwks_cache_seconds: int = Field(default=600, gt=0)
    jwks_timeout_seconds: float = Field(default=5.0, gt=0)

    # Supabase Storage for uploaded PDFs (NFR-09). The secret key is used server-side only
    # (D-049); without it, document endpoints return 503. Required when ENVIRONMENT=prod.
    supabase_secret_key: SecretStr | None = None
    # Private bucket, created by the team (docs/SETUP.md), never from code.
    storage_bucket: str = "documents"
    storage_timeout_seconds: float = Field(default=30.0, gt=0)
    # Lifetime of the signed URL returned by `GET /documents/{id}/file`.
    signed_url_ttl_seconds: int = Field(default=300, gt=0)

    # Uploads (FR-03) and background ingestion (SRS §8.1).
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    # Ingestions running at once; later uploads wait in status "uploaded".
    ingestion_concurrency: int = Field(default=1, gt=0)
    # In-progress documents not updated for this long are marked failed (D-049, D-058).
    ingestion_stale_minutes: int = Field(default=15, ge=0)
    # How often a running app repeats that sweep, so a stuck document can be uploaded again.
    ingestion_sweep_interval_minutes: float = Field(default=5, gt=0)

    # Two LLM tiers (D-031): "fast" for A1-style calls, "strong" for synthesis and judging.
    # "fake" is the strict test double; "demo" gives canned, visibly marked replies for key-free
    # local runs and is refused in prod (D-062).
    llm_fast_provider: LLMProviderName = "fake"
    llm_fast_model: str = "openai/gpt-oss-20b"
    llm_strong_provider: LLMProviderName = "fake"
    llm_strong_model: str = "gemini-3.5-flash-lite"
    # Required when a tier selects that provider (checked when providers are built).
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    # Retries after the first attempt on rate limits, 5xx, timeouts (SRS §20).
    llm_max_retries: int = Field(default=2, ge=0)
    llm_retry_base_seconds: float = Field(default=1.0, ge=0)
    # Client-side limits per tier model (0 = unlimited); providers set quotas per model.
    # Defaults are the free-tier limits seen on 2026-10-04: Groq docs for gpt-oss-20b, the
    # team's AI Studio dashboard for gemini-3.5-flash-lite. Tiers on the same model share one
    # limiter with the fast tier's limits.
    llm_fast_rpm: int = Field(default=30, ge=0)
    llm_fast_tpm: int = Field(default=8000, ge=0)
    llm_fast_rpd: int = Field(default=1000, ge=0)
    llm_strong_rpm: int = Field(default=15, ge=0)
    llm_strong_tpm: int = Field(default=250_000, ge=0)
    llm_strong_rpd: int = Field(default=500, ge=0)
    # Graph tier (SRS §9.1, D-081, D-083): knowledge graph extraction only, with its own rate
    # limiter so a graph job never waits in or drains the interactive tiers' quota. A hosted
    # graph model must differ from the fast and strong models unless LLM_GRAPH_API_KEY (another
    # key, so another quota) is set; without it the provider's key above is used. "fake" (the
    # default) leaves graph generation off. The limits are provisional until a model is chosen.
    llm_graph_provider: GraphLLMProviderName = "fake"
    llm_graph_model: str = ""
    llm_graph_api_key: SecretStr | None = None
    llm_graph_rpm: int = Field(default=10, ge=0)
    llm_graph_tpm: int = Field(default=8000, ge=0)
    llm_graph_rpd: int = Field(default=300, ge=0)
    # Graph-tier retries only: hosted overloads (e.g. Gemma 503s) last minutes, and a job has no
    # user waiting, so it backs off longer than chat (10, 20, 40, 80 s by default).
    llm_graph_max_retries: int = Field(default=4, ge=0)
    llm_graph_retry_base_seconds: float = Field(default=10.0, ge=0)
    # LangSmith tracing (FR-28). Copied into the LANGSMITH_* variables LangChain reads.
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "research-assistant"
    embedding_provider: EmbeddingProviderName = "fake"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Must match the `chunks.embedding` column; changing it needs a migration (D-013, D-050).
    embedding_dimension: int = Field(default=384, gt=0)
    # bge models expect this instruction before queries (not before passages).
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    embedding_batch_size: int = Field(default=16, gt=0)
    reranker_provider: RerankerProviderName = "fake"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Query + passage tokens; longer pairs are truncated.
    reranker_max_length: int = Field(default=512, gt=0)
    reranker_batch_size: int = Field(default=16, gt=0)
    # Hybrid retrieval (SRS §8.2): candidates per search, RRF constant, fused candidates passed
    # to the reranker per sub-question, and the evidence kept after reranking.
    dense_top_k: int = Field(default=30, gt=0)
    lexical_top_k: int = Field(default=30, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    rerank_candidates: int = Field(default=20, gt=0)
    retrieval_top_k: int = Field(default=8, gt=0)
    # S3 sufficiency gate (FR-10, D-065): a best reranker score at or above the fast-pass
    # score counts as covered without an LLM call; other sub-questions go to the LLM check,
    # which reads their best chunks (all of the evidence A2 gets). The fast-pass score is
    # provisional until the calibration split is human-verified.
    sufficiency_fast_pass_score: float = Field(default=0.97, ge=0, le=1)
    sufficiency_check_chunks: int = Field(default=8, gt=0)
    # S5 citation quote: the cited chunk's sentence closest to the claim, cut to this length.
    citation_quote_max_chars: int = Field(default=300, gt=0)
    # A4 comparison (FR-19): evidence chunks retrieved per paper × attribute; papers per
    # comparison or synthesis. A4 synthesis (FR-18): evidence chunks retrieved per paper.
    compare_top_k: int = Field(default=3, gt=0)
    compare_max_papers: int = Field(default=5, ge=2)
    synthesis_top_k: int = Field(default=4, gt=0)
    # A4 contradictions (FR-20): findings kept per paper, the NLI contradiction score a pair of
    # findings needs to reach the LLM context check, and the most pairs checked per run.
    contradiction_findings_per_paper: int = Field(default=3, gt=0)
    contradiction_nli_score: float = Field(default=0.5, ge=0, le=1)
    contradiction_max_pairs: int = Field(default=10, gt=0)
    # A3 verification (FR-12, D-067): NLI entailment bands per claim (at or above the supported
    # score: supported; below the unsupported score: unsupported; in between, or contradicted
    # by a cited chunk at or above the contradiction score: the batched LLM judge), the NLI
    # premise window in words, and the claims an answer needs to be kept after the last loop.
    # The unsupported band is off (0): NLI scored too many supported claims near 0 to reject
    # any claim without the judge.
    verification_supported_score: float = Field(default=0.9, ge=0, le=1)
    verification_unsupported_score: float = Field(default=0.0, ge=0, le=1)
    verification_contradiction_score: float = Field(default=0.5, ge=0, le=1)
    verification_window_words: int = Field(default=120, gt=0)
    verification_min_claims: int = Field(default=1, ge=0)
    # A2 rewrites after A3 finds unsupported or partial claims at most this often (SRS §7.3).
    verification_max_revisions: int = Field(default=2, ge=0)
    # QA runs (SRS §5.4). Checkpoints live in the `langgraph` schema; the pool serves only the
    # checkpointer. A `running` run older than the stale time that this process is not running
    # is marked failed at startup and every sweep interval; `interrupted` runs wait for the
    # user indefinitely (SRS §20).
    checkpoint_pool_size: int = Field(default=4, gt=0)
    qa_run_stale_minutes: int = Field(default=15, ge=0)
    qa_run_sweep_interval_minutes: float = Field(default=5, gt=0)
    # Knowledge graph jobs (SRS §9.1, D-081). A running job writes a heartbeat this often, also
    # while it waits for rate limits; queued or running jobs this process is not running whose
    # heartbeat is older than the stale time are failed at startup and every sweep interval.
    # Each job may make at most this many graph-tier LLM calls.
    kg_heartbeat_seconds: float = Field(default=60, gt=0)
    kg_job_stale_minutes: int = Field(default=10, gt=0)
    kg_job_sweep_interval_minutes: float = Field(default=5, gt=0)
    kg_max_calls_per_job: int = Field(default=150, gt=0)
    # Extraction (SRS §9.1, D-083): passages shorter than this many words are skipped; at most
    # this many passages of a paper are read, this many per LLM call, with this output cap.
    kg_min_chunk_words: int = Field(default=40, ge=0)
    kg_max_chunks_per_paper: int = Field(default=60, gt=0)
    kg_chunks_per_call: int = Field(default=4, gt=0)
    kg_max_output_tokens: int = Field(default=3000, gt=0)
    # A relationship is kept only if NLI scores its quote as entailing its statement at or above
    # this score and contradicting it below the other; both provisional until calibrated.
    kg_relation_entailment_score: float = Field(default=0.9, ge=0, le=1)
    kg_relation_contradiction_score: float = Field(default=0.5, ge=0, le=1)
    # Most nodes the graph endpoint returns (the most-supported first).
    kg_graph_max_nodes: int = Field(default=500, gt=0)
    # Longest accepted query (S6 input check).
    max_query_chars: int = Field(default=1000, gt=0)
    nli_provider: NLIProviderName = "fake"
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    nli_max_length: int = Field(default=512, gt=0)
    nli_batch_size: int = Field(default=16, gt=0)
    # Local models: load weights at startup (Docker) or on first use (local dev) (D-035).
    preload_models: bool = False
    # Local inference calls running at once; others wait. Small CPUs gain nothing from more.
    local_inference_concurrency: int = Field(default=1, gt=0)
    # Run the CPU benchmark once in the background at startup and log the table (D-024).
    run_benchmark_on_startup: bool = False
    parser_provider: ParserProviderName = "fake"
    # Below this average of extractable characters per page, a PDF is rejected as scanned.
    pdf_min_text_chars_per_page: int = Field(default=100, ge=0)
    # A short line on at least this many pages, and this share of pages, is a running
    # header/footer or margin text and is removed before chunking.
    boilerplate_min_pages: int = Field(default=3, ge=2)
    boilerplate_min_page_fraction: float = Field(default=0.5, gt=0, le=1)
    boilerplate_max_line_chars: int = Field(default=200, gt=0)
    # Chunk size in embedding-model tokens, and overlap as a share of the target (D-044).
    chunk_min_tokens: int = Field(default=350, gt=0)
    chunk_max_tokens: int = Field(default=450, gt=0)
    chunk_overlap_ratio: float = Field(default=0.12, ge=0, lt=0.5)
    # Chunks shorter than this merge into a neighbour in the same section.
    chunk_merge_below_tokens: int = Field(default=80, ge=0)
    # Merged chunks never exceed this: bge-small and MiniLM take 512 tokens incl. [CLS]/[SEP].
    chunk_hard_max_tokens: int = Field(default=510, gt=0)
    # Document compatibility (S7, FR-22, SRS §11.2). A document's topic vector is the mean of
    # its first chunks (abstract and first section); the upload check parses only the first
    # pages. Below the threshold (cosine to the workspace centroid) the user is warned.
    compatibility_chunks: int = Field(default=4, gt=0)
    compatibility_max_pages: int = Field(default=3, gt=0)
    compatibility_threshold: float = Field(default=0.83, ge=-1, le=1)
    # S7 keyword summary (D-068): the titles and first chunks of up to this many ready
    # documents (each cut to the character limit) go to one strong-tier call.
    topic_summary_max_documents: int = Field(default=20, gt=0)
    topic_summary_chars_per_document: int = Field(default=1500, gt=0)
    # Scholarly APIs; web search is separate because it needs approval (D-032).
    search_provider: SearchProviderName = "fake"
    # Sent to Crossref/OpenAlex for their "polite pool" (User-Agent and mailto).
    # Required when SEARCH_PROVIDER=live.
    contact_email: str | None = None
    scholarly_timeout_seconds: float = Field(default=5.0, gt=0)
    # Optional free OpenAlex key (openalex.org/settings/api): 10x the keyless daily budget
    # (about 1,000 instead of 100 searches a day). Sent to OpenAlex only, never to clients.
    openalex_api_key: SecretStr | None = None
    # Discover search and paper lookups (D-077): OpenAlex searches sometimes exceed 5 s.
    discover_timeout_seconds: float = Field(default=15.0, gt=0)
    # DOI candidates from pages 1-2 checked against the lookup per document.
    doi_max_candidates: int = Field(default=3, gt=0)
    # First-page LLM metadata (FR-04, D-068), used when no DOI is confirmed: characters of
    # page 1 sent to the fast tier.
    metadata_llm_max_chars: int = Field(default=6000, gt=0)
    web_search_provider: WebSearchProviderName = "fake"
    # Discover (D-077): results per source, arXiv's requested pacing (one call per 3 s), and
    # PDF import downloads (size cap is MAX_UPLOAD_BYTES).
    discover_max_results: int = Field(default=10, gt=0, le=50)
    arxiv_requests_per_minute: int = Field(default=20, ge=0)
    import_max_redirects: int = Field(default=3, ge=0, le=10)
    # Time for checking that listed PDFs really answer, for all results of one search.
    discover_pdf_check_seconds: float = Field(default=4.0, gt=0)
    import_timeout_seconds: float = Field(default=30.0, gt=0)
    # One whole PDF download (a slow host cannot hold it longer), and all of an import's
    # PDF locations together.
    import_download_deadline_seconds: float = Field(default=90.0, gt=0)
    import_budget_seconds: float = Field(default=120.0, gt=0)
    # Evaluation (FR-27, SRS §17.3): the Ragas judge must not be A3's model (the strong tier),
    # so a judgment never checks itself. Limits are Groq's free tier for gpt-oss-120b. Answer
    # relevancy asks the judge this many times per answer (Ragas default 3).
    eval_judge_provider: LLMProviderName = "fake"
    eval_judge_model: str = "openai/gpt-oss-120b"
    eval_judge_rpm: int = Field(default=30, ge=0)
    eval_judge_tpm: int = Field(default=8000, ge=0)
    eval_judge_rpd: int = Field(default=1000, ge=0)
    eval_answer_relevancy_strictness: int = Field(default=3, gt=0)

    @model_validator(mode="before")
    @classmethod
    def _strip_strings(cls, data: object) -> object:
        """Strip surrounding whitespace from every string value (a stray space or CRLF in .env)."""
        if isinstance(data, dict):
            return {
                key: value.strip() if isinstance(value, str) else value
                for key, value in data.items()
            }
        return data

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string or a JSON list for `CORS_ORIGINS`."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _empty_database_url_is_none(cls, value: object) -> object:
        """Treat an empty `DATABASE_URL=` line as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("contact_email", mode="before")
    @classmethod
    def _empty_contact_email_is_none(cls, value: object) -> object:
        """Treat an empty `CONTACT_EMAIL=` line as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "groq_api_key",
        "gemini_api_key",
        "llm_graph_api_key",
        "langsmith_api_key",
        "openalex_api_key",
        mode="before",
    )
    @classmethod
    def _empty_api_key_is_none(cls, value: object) -> object:
        """Treat an empty key line as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("supabase_secret_key", mode="before")
    @classmethod
    def _empty_secret_key_is_none(cls, value: object) -> object:
        """Treat an empty `SUPABASE_SECRET_KEY=` line as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("supabase_url", "supabase_jwks_url", mode="before")
    @classmethod
    def _normalize_url(cls, value: object) -> object:
        """Treat an empty value as not configured and drop a trailing slash."""
        if isinstance(value, str):
            stripped = value.strip().rstrip("/")
            return stripped or None
        return value

    @model_validator(mode="after")
    def _chunk_bounds_ordered(self) -> "Settings":
        """The chunker needs a non-empty token range."""
        if self.chunk_min_tokens > self.chunk_max_tokens:
            raise ValueError("CHUNK_MIN_TOKENS must not exceed CHUNK_MAX_TOKENS")
        if self.chunk_max_tokens > self.chunk_hard_max_tokens:
            raise ValueError("CHUNK_MAX_TOKENS must not exceed CHUNK_HARD_MAX_TOKENS")
        return self

    @model_validator(mode="after")
    def _verification_bands_ordered(self) -> "Settings":
        """A3's NLI bands must not overlap."""
        if self.verification_unsupported_score > self.verification_supported_score:
            raise ValueError(
                "VERIFICATION_UNSUPPORTED_SCORE must not exceed VERIFICATION_SUPPORTED_SCORE"
            )
        return self

    @model_validator(mode="after")
    def _graph_tier_has_its_own_quota(self) -> "Settings":
        """A graph model shared with an interactive tier needs its own key (D-083)."""
        if self.llm_graph_provider == "fake" or self.llm_graph_api_key is not None:
            return self
        graph = (self.llm_graph_provider, self.llm_graph_model)
        interactive = {
            (self.llm_fast_provider, self.llm_fast_model),
            (self.llm_strong_provider, self.llm_strong_model),
        }
        if graph in interactive:
            raise ValueError(
                "LLM_GRAPH_MODEL must differ from LLM_FAST_MODEL and LLM_STRONG_MODEL unless "
                "LLM_GRAPH_API_KEY is set, so graph jobs cannot use up interactive quota"
            )
        return self

    @model_validator(mode="after")
    def _heartbeat_within_stale_time(self) -> "Settings":
        """A running job must write heartbeats more often than the sweep calls it stale."""
        if self.kg_heartbeat_seconds >= self.kg_job_stale_minutes * 60:
            raise ValueError("KG_HEARTBEAT_SECONDS must be shorter than KG_JOB_STALE_MINUTES")
        return self

    @model_validator(mode="after")
    def _live_search_requires_contact_email(self) -> "Settings":
        """Crossref and OpenAlex ask API users to identify themselves."""
        if self.search_provider == "live" and self.contact_email is None:
            raise ValueError("CONTACT_EMAIL is required when SEARCH_PROVIDER=live")
        return self

    @model_validator(mode="after")
    def _no_demo_llm_in_prod(self) -> "Settings":
        """Canned demo answers must never reach real users."""
        demo = "demo" in (self.llm_fast_provider, self.llm_strong_provider)
        if self.environment == "prod" and demo:
            raise ValueError("The demo LLM provider is not allowed when ENVIRONMENT=prod")
        return self

    @model_validator(mode="after")
    def _tracing_requires_key(self) -> "Settings":
        """LangSmith rejects untraceable runs silently; fail at startup instead."""
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("LANGSMITH_API_KEY is required when LANGSMITH_TRACING=true")
        return self

    @model_validator(mode="after")
    def _prod_requires_auth(self) -> "Settings":
        """Production must never serve authenticated endpoints without token verification."""
        if self.environment == "prod" and self.supabase_url is None:
            raise ValueError("SUPABASE_URL is required when ENVIRONMENT=prod")
        return self

    @model_validator(mode="after")
    def _prod_requires_storage(self) -> "Settings":
        """Production must be able to store uploaded documents."""
        if self.environment == "prod" and self.supabase_secret_key is None:
            raise ValueError("SUPABASE_SECRET_KEY is required when ENVIRONMENT=prod")
        return self

    @property
    def jwt_issuer(self) -> str | None:
        """Issuer claim Supabase Auth puts in access tokens."""
        return None if self.supabase_url is None else f"{self.supabase_url}/auth/v1"

    @property
    def jwks_url(self) -> str | None:
        """Where the project's public signing keys are published."""
        if self.supabase_jwks_url is not None:
            return self.supabase_jwks_url
        issuer = self.jwt_issuer
        return None if issuer is None else f"{issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
