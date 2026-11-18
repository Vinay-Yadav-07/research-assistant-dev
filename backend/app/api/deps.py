"""FastAPI dependencies shared by routers."""

from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import BackgroundTasks, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.literature_analysis import LiteratureAnalysisAgent
from app.core.auth import CurrentUser, JWTVerifier
from app.core.config import Settings
from app.core.errors import AuthenticationError, DependencyUnavailableError
from app.graphs.qa_runner import QARun, QARunner
from app.providers.factory import Providers, build_pdf_fetcher
from app.providers.fetch import PdfFetcher
from app.repositories.chunks import ChunkRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.documents import DocumentRepository
from app.repositories.health import DatabaseHealthRepository
from app.repositories.research import ResearchRepository
from app.repositories.topic_profiles import TopicProfileRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.conversations import MessageCreate, RunResume
from app.services.citations import CitationService
from app.services.compatibility import CompatibilityService
from app.services.conversations import ConversationService
from app.services.documents import DocumentService, FileStorage
from app.services.health import ReadinessService
from app.services.ingestion import IngestionOptions, IngestionService
from app.services.knowledge_graph_jobs import KnowledgeGraphRunner
from app.services.papers import PaperImportService
from app.services.research import ResearchService
from app.services.retrieval import RetrievalOptions, RetrievalService
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.topic_summary import TopicSummaryService
from app.services.workspaces import WorkspaceService

# auto_error=False so a missing token goes through our 401 envelope, not FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")


def get_app_settings(request: Request) -> Settings:
    """Return the settings the running app was created with."""
    return cast(Settings, request.app.state.settings)


def get_providers(request: Request) -> Providers:
    """Return the providers built at startup."""
    return cast(Providers, request.app.state.providers)


def get_readiness_service(request: Request) -> ReadinessService:
    """Build the readiness service from the app's database engine (None if not configured)."""
    settings = get_app_settings(request)
    engine = cast(AsyncEngine | None, request.app.state.db_engine)
    database = DatabaseHealthRepository(engine) if engine is not None else None
    return ReadinessService(database, timeout_seconds=settings.readiness_timeout_seconds)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    """Verify the bearer token; 401 if missing or invalid, 503 if auth is not configured."""
    verifier = cast(JWTVerifier | None, request.app.state.jwt_verifier)
    if verifier is None:
        raise DependencyUnavailableError("Authentication is not configured.")
    if credentials is None:
        raise AuthenticationError()
    return await verifier.verify(credentials.credentials)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request; anything not committed by a service is rolled back."""
    sessions = cast(async_sessionmaker[AsyncSession] | None, request.app.state.db_sessionmaker)
    if sessions is None:
        raise DependencyUnavailableError("The database is not configured.")
    async with sessions() as session:
        yield session


def get_storage(request: Request) -> FileStorage | None:
    """The document bucket client, or None when Storage is not configured."""
    return cast(FileStorage | None, request.app.state.storage)


def get_ingestion_service(request: Request) -> IngestionService:
    """The app-wide ingestion runner; 503 without a database."""
    ingestion = cast(IngestionService | None, request.app.state.ingestion)
    if ingestion is None:
        raise DependencyUnavailableError("The database is not configured.")
    return ingestion


def get_knowledge_graph_runner(request: Request) -> KnowledgeGraphRunner:
    """The app-wide knowledge graph job runner; 503 without a database."""
    runner = cast(KnowledgeGraphRunner | None, request.app.state.knowledge_graph)
    if runner is None:
        raise DependencyUnavailableError("The database is not configured.")
    return runner


def get_topic_summaries(request: Request) -> TopicSummaryService | None:
    """The app-wide keyword summary refresher, or None without a database."""
    return cast(TopicSummaryService | None, request.app.state.topic_summaries)


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[FileStorage | None, Depends(get_storage)],
) -> WorkspaceService:
    """Build the workspace service on the request's session."""
    return WorkspaceService(WorkspaceRepository(session), storage)


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[FileStorage | None, Depends(get_storage)],
    ingestion: Annotated[IngestionService, Depends(get_ingestion_service)],
    summaries: Annotated[TopicSummaryService | None, Depends(get_topic_summaries)],
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DocumentService:
    """Build the document service; new uploads are ingested, and keyword summaries refreshed,
    after the response is sent."""

    def schedule(user_id: UUID, document_id: UUID, data: bytes) -> None:
        background_tasks.add_task(ingestion.run, user_id, document_id, data)

    def schedule_summary(user_id: UUID, workspace_id: UUID) -> None:
        if summaries is not None:
            background_tasks.add_task(summaries.refresh, user_id, workspace_id)

    store = DocumentRepository(session)
    return DocumentService(
        store,
        storage,
        schedule,
        profiles=TopicProfileService(store.profiles, CompatibilityOptions.from_settings(settings)),
        signed_url_ttl_seconds=settings.signed_url_ttl_seconds,
        schedule_summary=schedule_summary,
    )


def get_compatibility_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    providers: Annotated[Providers, Depends(get_providers)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CompatibilityService:
    """Build the pre-upload compatibility check on the request's session."""
    return CompatibilityService(
        TopicProfileRepository(session),
        parser=providers.parser,
        embedder=providers.embedder,
        options=CompatibilityOptions.from_settings(settings),
        ingestion=IngestionOptions.from_settings(settings),
    )


def get_pdf_fetcher(settings: Annotated[Settings, Depends(get_app_settings)]) -> PdfFetcher:
    """The paper-import downloader (D-077)."""
    return build_pdf_fetcher(settings)


def get_paper_import_service(
    documents: Annotated[DocumentService, Depends(get_document_service)],
    compatibility: Annotated[CompatibilityService, Depends(get_compatibility_service)],
    providers: Annotated[Providers, Depends(get_providers)],
    fetcher: Annotated[PdfFetcher, Depends(get_pdf_fetcher)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> PaperImportService:
    """Build Discover's paper import on top of the upload and compatibility services."""
    return PaperImportService(
        providers.scholarly_search,
        fetcher,
        documents,
        compatibility,
        download_budget_seconds=settings.import_budget_seconds,
    )


def get_retrieval_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    providers: Annotated[Providers, Depends(get_providers)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> RetrievalService:
    """Build the retrieval service on the request's session."""
    return RetrievalService(
        ChunkRepository(session),
        embedder=providers.embedder,
        reranker=providers.reranker,
        options=RetrievalOptions.from_settings(settings),
    )


def get_literature_analysis_agent(
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
    providers: Annotated[Providers, Depends(get_providers)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> LiteratureAnalysisAgent:
    """Build A4 on the strong-tier LLM and the request's retrieval service."""
    return LiteratureAnalysisAgent(
        providers.llm_strong,
        retrieval,
        CitationService.from_settings(settings),
        compare_top_k=settings.compare_top_k,
        compare_max_papers=settings.compare_max_papers,
        synthesis_top_k=settings.synthesis_top_k,
        nli=providers.nli,
        contradiction_findings_per_paper=settings.contradiction_findings_per_paper,
        contradiction_nli_score=settings.contradiction_nli_score,
        contradiction_max_pairs=settings.contradiction_max_pairs,
    )


def get_research_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResearchService:
    """Build the research output service on the request's session."""
    return ResearchService(ResearchRepository(session))


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationService:
    """Build the chat history service on the request's session."""
    return ConversationService(ConversationRepository(session))


def get_qa_runner(request: Request) -> QARunner:
    """The app-wide QA graph runner; 503 without a database."""
    runner = cast(QARunner | None, request.app.state.qa_runner)
    if runner is None:
        raise DependencyUnavailableError("The database is not configured.")
    return runner


async def start_qa_run(
    conversation_id: UUID,
    body: MessageCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    runner: Annotated[QARunner, Depends(get_qa_runner)],
) -> QARun:
    """Ask the question before the stream opens, so a rejection is a plain error response."""
    return await runner.start(user.id, conversation_id, body.content)


async def resume_qa_run(
    run_id: UUID,
    body: RunResume,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    runner: Annotated[QARunner, Depends(get_qa_runner)],
) -> QARun:
    """Record the approval decision before the stream opens (404, 409, or 422 otherwise)."""
    return await runner.resume(user.id, run_id, body.decision)
