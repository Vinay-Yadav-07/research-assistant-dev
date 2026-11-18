"""FastAPI application factory. Run with `uv run uvicorn app.main:app --reload`."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.query_analyzer import QueryAnalyzer
from app.agents.synthesis import SynthesisAgent
from app.agents.verification import VerificationAgent, VerificationOptions
from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.core.auth import JWTVerifier, http_jwks_fetcher
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.graphs.qa import QAContext, build_qa_graph
from app.graphs.qa_runner import QARunner
from app.providers.factory import Providers, build_providers, preload_models
from app.providers.local.benchmark import log_startup_benchmark
from app.providers.tracing import configure_tracing
from app.repositories.checkpoints import (
    CheckpointPool,
    create_checkpoint_pool,
    create_checkpointer,
)
from app.repositories.chunks import ChunkRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import document_store_factory
from app.repositories.knowledge_graph import knowledge_graph_store_factory
from app.repositories.storage import create_storage_from_settings
from app.repositories.topic_profiles import topic_profile_store_factory
from app.services.citations import CitationService
from app.services.conversations import ConversationService
from app.services.document_metadata import FirstPageExtractor, MetadataService
from app.services.ingestion import IngestionOptions, IngestionService
from app.services.knowledge_graph import (
    EXTRACTOR_VERSION,
    KGExtractionOptions,
    KnowledgeGraphExtractor,
)
from app.services.knowledge_graph_build import KnowledgeGraphBuilder
from app.services.knowledge_graph_jobs import KGJobOptions, KnowledgeGraphRunner
from app.services.retrieval import RetrievalOptions, RetrievalService
from app.services.sufficiency import SufficiencyGate, SufficiencyOptions
from app.services.topic_profile import CompatibilityOptions
from app.services.topic_summary import TopicSummaryOptions, TopicSummaryService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass explicit settings; production reads the environment."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_tracing(settings)
        app.state.providers = build_providers(settings)
        background: list[asyncio.Task[None]] = []
        if settings.preload_models:
            await asyncio.to_thread(preload_models, app.state.providers)
        engine = create_engine_from_settings(settings)
        app.state.db_engine = engine
        app.state.db_sessionmaker = create_sessionmaker(engine) if engine is not None else None
        checkpoint_pool = create_checkpoint_pool(settings)
        if checkpoint_pool is not None and app.state.db_sessionmaker is not None:
            # Opens in the background, so an unreachable database does not block startup.
            await checkpoint_pool.open(wait=False)
            app.state.qa_runner = build_qa_runner(
                settings, app.state.providers, app.state.db_sessionmaker, checkpoint_pool
            )
            stale_runs = timedelta(minutes=settings.qa_run_stale_minutes)
            try:
                await app.state.qa_runner.fail_stale(stale_runs)
            except Exception:
                logger.exception("Startup sweep of stale QA runs failed")
            background.append(
                asyncio.create_task(
                    app.state.qa_runner.sweep_periodically(
                        settings.qa_run_sweep_interval_minutes * 60, stale_runs
                    )
                )
            )
        if app.state.db_sessionmaker is not None:
            app.state.topic_summaries = build_topic_summaries(
                settings, app.state.providers, app.state.db_sessionmaker
            )
            app.state.ingestion = build_ingestion(
                settings,
                app.state.providers,
                app.state.db_sessionmaker,
                summaries=app.state.topic_summaries,
            )
            try:
                await app.state.ingestion.fail_stale()
            except Exception:
                logger.exception("Startup sweep of interrupted ingestions failed")
            background.append(
                asyncio.create_task(
                    app.state.ingestion.sweep_periodically(
                        settings.ingestion_sweep_interval_minutes * 60
                    )
                )
            )
            app.state.knowledge_graph = build_knowledge_graph(
                settings, app.state.providers, app.state.db_sessionmaker
            )
            try:
                await app.state.knowledge_graph.fail_stale()
            except Exception:
                logger.exception("Startup sweep of interrupted knowledge graph jobs failed")
            background.append(
                asyncio.create_task(
                    app.state.knowledge_graph.sweep_periodically(
                        settings.kg_job_sweep_interval_minutes * 60
                    )
                )
            )
        if settings.run_benchmark_on_startup:
            background.append(asyncio.create_task(log_startup_benchmark(app.state.providers)))
        try:
            yield
        finally:
            for task in background:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if app.state.qa_runner is not None:
                await app.state.qa_runner.aclose()
            if app.state.knowledge_graph is not None:
                await app.state.knowledge_graph.aclose()
            if checkpoint_pool is not None:
                await checkpoint_pool.close()
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.db_engine = None
    app.state.db_sessionmaker = None
    app.state.providers = None
    app.state.ingestion = None
    app.state.topic_summaries = None
    app.state.qa_runner = None
    app.state.knowledge_graph = None
    app.state.storage = create_storage_from_settings(settings)
    app.state.jwt_verifier = build_jwt_verifier(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


def build_topic_summaries(
    settings: Settings, providers: Providers, sessions: async_sessionmaker[AsyncSession]
) -> TopicSummaryService:
    """The workspace keyword summary refresher shared by all requests (S7, D-068)."""
    return TopicSummaryService(
        topic_profile_store_factory(sessions),
        providers.llm_strong,
        TopicSummaryOptions.from_settings(settings),
    )


def build_ingestion(
    settings: Settings,
    providers: Providers,
    sessions: async_sessionmaker[AsyncSession],
    *,
    summaries: TopicSummaryService | None = None,
) -> IngestionService:
    """The background ingestion runner shared by all requests.

    Without `summaries`, it gets a keyword summary refresher of its own.
    """
    return IngestionService(
        document_store_factory(sessions),
        parser=providers.parser,
        embedder=providers.embedder,
        metadata=MetadataService(
            providers.scholarly_search,
            max_candidates=settings.doi_max_candidates,
            first_page=FirstPageExtractor(
                providers.llm_fast, max_chars=settings.metadata_llm_max_chars
            ),
        ),
        options=IngestionOptions.from_settings(settings),
        compatibility=CompatibilityOptions.from_settings(settings),
        summaries=summaries or build_topic_summaries(settings, providers, sessions),
    )


def build_knowledge_graph(
    settings: Settings, providers: Providers, sessions: async_sessionmaker[AsyncSession]
) -> KnowledgeGraphRunner:
    """The knowledge graph job runner shared by all requests (S10, SRS §9.1).

    With the graph tier left at "fake", generation is off: the state can be read and starting
    a job answers 503.
    """
    stores = knowledge_graph_store_factory(sessions)
    enabled = settings.llm_graph_provider != "fake"
    return KnowledgeGraphRunner(
        stores,
        extractor=KnowledgeGraphExtractor(
            providers.llm_graph,
            providers.nli,
            CitationService.from_settings(settings),
            KGExtractionOptions.from_settings(settings),
        )
        if enabled
        else None,
        builder=KnowledgeGraphBuilder(stores, EXTRACTOR_VERSION) if enabled else None,
        options=KGJobOptions.from_settings(settings),
    )


def build_qa_runner(
    settings: Settings,
    providers: Providers,
    sessions: async_sessionmaker[AsyncSession],
    checkpoint_pool: CheckpointPool,
) -> QARunner:
    """The QA graph runner shared by all requests; each step opens its own session."""
    retrieval_options = RetrievalOptions.from_settings(settings)

    @asynccontextmanager
    async def open_retrieval() -> AsyncIterator[RetrievalService]:
        async with sessions() as session:
            yield RetrievalService(
                ChunkRepository(session),
                embedder=providers.embedder,
                reranker=providers.reranker,
                options=retrieval_options,
            )

    @asynccontextmanager
    async def open_conversations() -> AsyncIterator[ConversationService]:
        async with sessions() as session:
            yield ConversationService(ConversationRepository(session))

    context = QAContext(
        open_retrieval=open_retrieval,
        analyzer=QueryAnalyzer(providers.llm_fast),
        gate=SufficiencyGate(providers.llm_strong, SufficiencyOptions.from_settings(settings)),
        synthesis=SynthesisAgent(providers.llm_strong),
        verifier=VerificationAgent(
            providers.nli, providers.llm_strong, VerificationOptions.from_settings(settings)
        ),
        citations=CitationService.from_settings(settings),
        max_revisions=settings.verification_max_revisions,
    )
    return QARunner(
        build_qa_graph(create_checkpointer(checkpoint_pool)),
        context,
        open_conversations,
        max_question_chars=settings.max_query_chars,
    )


def build_jwt_verifier(settings: Settings) -> JWTVerifier | None:
    """The token verifier, or None when Supabase Auth is not configured (never in prod)."""
    if settings.jwt_issuer is None or settings.jwks_url is None:
        return None
    return JWTVerifier(
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        fetch_jwks=http_jwks_fetcher(
            settings.jwks_url, timeout_seconds=settings.jwks_timeout_seconds
        ),
        cache_seconds=settings.jwks_cache_seconds,
        leeway_seconds=settings.jwt_leeway_seconds,
    )


app = create_app()
