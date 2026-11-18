"""Builds provider implementations from settings.

Construction must stay cheap: it only checks configuration and creates objects. Heavy local
model weights are loaded lazily, or at startup when `PRELOAD_MODELS` is on (D-035).
Real implementations are imported inside their branch so their libraries load only when selected.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.providers.embedding import EmbeddingProvider
from app.providers.fakes import (
    FakeEmbedder,
    FakeLLM,
    FakeNLI,
    FakeParser,
    FakePdfFetcher,
    FakeReranker,
    FakeScholarlySearch,
    FakeWebSearch,
)
from app.providers.fetch import PdfFetcher
from app.providers.llm import LLMProvider, ModelTier
from app.providers.local.runtime import LocalInference, LocalModel, cached_hidden_size
from app.providers.nli import NLIProvider
from app.providers.parser import DocumentParser
from app.providers.rate_limit import RateLimiter
from app.providers.reranker import RerankerProvider
from app.providers.search import ScholarlySearchProvider, WebSearchProvider


@dataclass(frozen=True)
class Providers:
    """Every provider the application uses, built once at startup."""

    llm_fast: LLMProvider
    llm_strong: LLMProvider
    # Knowledge graph extraction only (SRS §9.1).
    llm_graph: LLMProvider
    embedder: EmbeddingProvider
    reranker: RerankerProvider
    nli: NLIProvider
    parser: DocumentParser
    scholarly_search: ScholarlySearchProvider
    web_search: WebSearchProvider


def build_providers(settings: Settings) -> Providers:
    """Build all providers, failing fast if any configured provider is unavailable."""
    inference = LocalInference(settings.local_inference_concurrency)
    limiters: dict[tuple[str, str], RateLimiter] = {}
    return Providers(
        llm_fast=build_llm(settings, "fast", limiters),
        llm_strong=build_llm(settings, "strong", limiters),
        llm_graph=build_graph_llm(settings),
        embedder=build_embedder(settings, inference),
        reranker=build_reranker(settings, inference),
        nli=build_nli(settings, inference),
        parser=build_parser(settings),
        scholarly_search=build_scholarly_search(settings),
        web_search=build_web_search(settings),
    )


def build_llm(
    settings: Settings,
    tier: ModelTier,
    limiters: dict[tuple[str, str], RateLimiter] | None = None,
) -> LLMProvider:
    """Build the chat model for one tier ("fast" or "strong").

    Providers set quotas per model, so tiers on the same (provider, model) share one rate
    limiter from `limiters`; the first tier built sets its limits.
    """
    fast = tier == "fast"
    name = settings.llm_fast_provider if fast else settings.llm_strong_provider
    model = settings.llm_fast_model if fast else settings.llm_strong_model
    limiters = {} if limiters is None else limiters
    match name:
        case "fake":
            return FakeLLM(model_name=f"fake-llm-{tier}")
        case "demo":
            from app.providers.fakes.demo_llm import DemoLLM

            return DemoLLM(model_name=f"demo-llm-{tier}")
        case "groq" | "gemini":
            from app.providers.live.llm_factory import build_hosted_llm

            key = (name, model)
            if key not in limiters:
                limiters[key] = _limiter(settings, tier)
            return build_hosted_llm(settings, name, model, tier, limiters[key])


def build_graph_llm(settings: Settings) -> LLMProvider:
    """Build the graph tier (D-083). Its rate limiter is its own, never shared with fast or
    strong, even on the same model (which needs another key, so another provider quota)."""
    match settings.llm_graph_provider:
        case "fake":
            return FakeLLM(model_name="fake-llm-graph")
        case "groq" | "gemini" as name:
            from app.providers.live.llm_factory import build_hosted_llm

            limiter = RateLimiter(
                requests_per_minute=settings.llm_graph_rpm,
                tokens_per_minute=settings.llm_graph_tpm,
                requests_per_day=settings.llm_graph_rpd,
            )
            return build_hosted_llm(
                settings,
                name,
                settings.llm_graph_model,
                "graph",
                limiter,
                api_key=settings.llm_graph_api_key,
                # A refused reply is an invalid batch (retried once), not an outage (D-084).
                schema_rejections_are_output_errors=True,
                max_retries=settings.llm_graph_max_retries,
                retry_base_seconds=settings.llm_graph_retry_base_seconds,
            )


def _limiter(settings: Settings, tier: ModelTier) -> RateLimiter:
    if tier == "fast":
        rpm, tpm, rpd = settings.llm_fast_rpm, settings.llm_fast_tpm, settings.llm_fast_rpd
    else:
        rpm, tpm, rpd = settings.llm_strong_rpm, settings.llm_strong_tpm, settings.llm_strong_rpd
    return RateLimiter(requests_per_minute=rpm, tokens_per_minute=tpm, requests_per_day=rpd)


def build_embedder(settings: Settings, inference: LocalInference) -> EmbeddingProvider:
    """Build the embedding model.

    A dimension mismatch is caught here if the model config is already cached; otherwise when
    the weights load. Building never loads weights.
    """
    match settings.embedding_provider:
        case "fake":
            return FakeEmbedder(dimension=settings.embedding_dimension)
        case "sentence_transformers":
            from app.providers.local import SentenceTransformerEmbedder

            hidden_size = cached_hidden_size(settings.embedding_model)
            if hidden_size is not None and hidden_size != settings.embedding_dimension:
                raise ProviderConfigurationError(
                    f"Embedding model '{settings.embedding_model}' has dimension {hidden_size} "
                    f"but EMBEDDING_DIMENSION is {settings.embedding_dimension}.",
                    details={"model": settings.embedding_model, "model_dimension": hidden_size},
                )
            return SentenceTransformerEmbedder(
                model_id=settings.embedding_model,
                dimension=settings.embedding_dimension,
                query_prefix=settings.embedding_query_prefix,
                batch_size=settings.embedding_batch_size,
                inference=inference,
            )


def build_reranker(settings: Settings, inference: LocalInference) -> RerankerProvider:
    """Build the reranker."""
    match settings.reranker_provider:
        case "fake":
            return FakeReranker()
        case "cross_encoder":
            from app.providers.local import CrossEncoderReranker

            return CrossEncoderReranker(
                model_id=settings.reranker_model,
                max_length=settings.reranker_max_length,
                batch_size=settings.reranker_batch_size,
                inference=inference,
            )


def build_nli(settings: Settings, inference: LocalInference) -> NLIProvider:
    """Build the NLI model."""
    match settings.nli_provider:
        case "fake":
            return FakeNLI()
        case "cross_encoder":
            from app.providers.local import CrossEncoderNLI

            return CrossEncoderNLI(
                model_id=settings.nli_model,
                max_length=settings.nli_max_length,
                batch_size=settings.nli_batch_size,
                inference=inference,
            )


def preload_models(providers: Providers) -> None:
    """Load every local model's weights now (blocking; run it in a worker thread)."""
    for provider in (providers.embedder, providers.reranker, providers.nli):
        if isinstance(provider, LocalModel):
            provider.load()


def build_parser(settings: Settings) -> DocumentParser:
    """Build the document parser."""
    match settings.parser_provider:
        case "fake":
            return FakeParser()
        case "pymupdf4llm":
            from app.providers.local.pdf_parser import PyMuPDF4LLMParser

            return PyMuPDF4LLMParser(min_text_chars_per_page=settings.pdf_min_text_chars_per_page)
        case name:
            raise _not_implemented("parser", name, phase=1)


def build_scholarly_search(settings: Settings) -> ScholarlySearchProvider:
    """Build the scholarly API client (DOI enrichment in Phase 1, discovery in Phase 5)."""
    match settings.search_provider:
        case "fake":
            return FakeScholarlySearch()
        case "live":
            from app.providers.live.scholarly import LiveScholarlySearch

            return LiveScholarlySearch(
                contact_email=settings.contact_email,
                timeout_seconds=settings.scholarly_timeout_seconds,
                discover_timeout_seconds=settings.discover_timeout_seconds,
                openalex_api_key=(
                    settings.openalex_api_key.get_secret_value()
                    if settings.openalex_api_key
                    else None
                ),
                arxiv_limiter=RateLimiter(
                    requests_per_minute=settings.arxiv_requests_per_minute, tokens_per_minute=0
                ),
            )


def build_pdf_fetcher(settings: Settings) -> PdfFetcher:
    """Build the paper-import downloader; it follows `SEARCH_PROVIDER` (D-077)."""
    match settings.search_provider:
        case "fake":
            return FakePdfFetcher()
        case "live":
            from app.providers.live.safe_fetch import SafePdfFetcher
            from app.providers.live.scholarly import user_agent

            return SafePdfFetcher(
                max_bytes=settings.max_upload_bytes,
                max_redirects=settings.import_max_redirects,
                timeout_seconds=settings.import_timeout_seconds,
                deadline_seconds=settings.import_download_deadline_seconds,
                user_agent=user_agent(settings.contact_email),
            )


def build_web_search(settings: Settings) -> WebSearchProvider:
    """Build the web search client. Callers must hold a Corpus + Web approval to use it."""
    match settings.web_search_provider:
        case "fake":
            return FakeWebSearch()
        case name:
            raise _not_implemented("web search", name, phase=5)


def _not_implemented(kind: str, name: str, *, phase: int) -> ProviderConfigurationError:
    return ProviderConfigurationError(
        f"{kind} provider '{name}' is not implemented yet (planned for Phase {phase}).",
        details={"provider": kind, "name": name},
    )
