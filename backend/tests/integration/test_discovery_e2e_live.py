"""Discover end to end on Supabase dev: search arXiv, import the paper's PDF into a fresh
workspace, wait for ingestion, then ask a question and get an answer cited from that paper.

Real network (arXiv), real parser, embedder and reranker, Groq (A1) and Gemini (S3, A2, A3).
Needs DATABASE_URL, SUPABASE_URL, SUPABASE_SECRET_KEY, CONTACT_EMAIL, GROQ_API_KEY and
GEMINI_API_KEY. The workspace is deleted afterwards. About 1-2 min and ~6 LLM calls:
`uv run pytest -m integration tests/integration/test_discovery_e2e_live.py -s`
"""

import asyncio
from uuid import UUID, uuid4

import pytest

from app.core.errors import ExternalServiceError
from app.graphs.qa_runner import ClaimsEvent, DoneEvent
from app.main import build_ingestion, build_qa_runner
from app.providers.factory import build_pdf_fetcher
from app.repositories.checkpoints import create_checkpoint_pool
from app.repositories.conversations import ConversationRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import DocumentRepository
from app.repositories.storage import create_storage_from_settings
from app.repositories.topic_profiles import TopicProfileRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.conversations import ConversationCreate
from app.services.compatibility import CompatibilityService
from app.services.conversations import ConversationService
from app.services.documents import DocumentService
from app.services.ingestion import IngestionOptions
from app.services.papers import PaperImportService, search_papers
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.workspaces import WorkspaceService
from tests.integration.live_corpora import live_providers, live_settings
from tests.integration.test_ingestion_supabase import wait_until_finished
from tests.integration.test_qa_graph_live import collect

pytestmark = pytest.mark.integration

ARXIV_ID = "1706.03762"  # "Attention Is All You Need", open access on arXiv
QUESTION = "What BLEU score does the Transformer reach on WMT 2014 English-to-German translation?"


async def test_search_import_ingest_and_cited_answer() -> None:
    settings = live_settings().model_copy(
        update={"llm_fast_provider": "groq", "search_provider": "live"}
    )
    if settings.groq_api_key is None or settings.contact_email is None:
        pytest.skip("GROQ_API_KEY or CONTACT_EMAIL not set")
    engine = create_engine_from_settings(settings)
    storage = create_storage_from_settings(settings)
    pool = create_checkpoint_pool(settings)
    if engine is None or storage is None or pool is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    providers = live_providers(settings)
    fetcher = build_pdf_fetcher(settings)
    try:
        found = await search_papers(
            providers.scholarly_search,
            fetcher,
            "Attention Is All You Need Vaswani",
            scope="arxiv",
            limit=5,
            pdf_check_seconds=10,
        )
    except ExternalServiceError as error:
        pytest.skip(f"arXiv unavailable: {error.message}")
    paper = next((p for p in found.results if p.external_id.startswith(ARXIV_ID)), None)
    assert paper is not None and paper.importable, [p.external_id for p in found.results]

    sessions = create_sessionmaker(engine)
    ingestion = build_ingestion(settings, providers, sessions)
    tasks: list[asyncio.Task[None]] = []

    def schedule(user_id: UUID, document_id: UUID, data: bytes) -> None:
        tasks.append(asyncio.create_task(ingestion.run(user_id, document_id, data)))

    await pool.open(wait=True, timeout=30)
    runner = build_qa_runner(settings, providers, sessions, pool)
    user = uuid4()
    async with sessions() as session:
        workspace = await WorkspaceRepository(session).create(
            user, name="Integration: discovery", description=None, default_mode="corpus_only"
        )
        workspace_id = workspace.id
        await session.commit()
    try:
        async with sessions() as session:
            store = DocumentRepository(session)
            options = CompatibilityOptions.from_settings(settings)
            service = PaperImportService(
                providers.scholarly_search,
                fetcher,
                DocumentService(
                    store,
                    storage,
                    schedule,
                    profiles=TopicProfileService(store.profiles, options),
                    signed_url_ttl_seconds=60,
                ),
                CompatibilityService(
                    TopicProfileRepository(session),
                    parser=providers.parser,
                    embedder=providers.embedder,
                    options=options,
                    ingestion=IngestionOptions.from_settings(settings),
                ),
            )
            imported = await service.import_paper(user, workspace_id, "arxiv", paper.external_id)
        assert imported.duplicate is False
        assert imported.document.source == "import"
        assert imported.document.source_url == f"https://arxiv.org/abs/{paper.external_id}"

        document = await wait_until_finished(sessions, user, imported.document.id)
        assert document.status == "ready", document.error
        print(f"\nimported {paper.external_id}: {document.title!r}, {document.page_count} pages")

        async with sessions() as session:
            conversation = await ConversationService(ConversationRepository(session)).create(
                user, workspace_id, ConversationCreate(title="Discovery e2e")
            )
        events, seconds = await collect(await runner.start(user, conversation.id, QUESTION))
        done = events[-1]
        assert isinstance(done, DoneEvent) and done.outcome == "answered", done
        claims = next(e for e in events if isinstance(e, ClaimsEvent)).claims
        cited = {c.document_id for claim in claims for c in claim.citations}
        assert cited == {document.id}
        assert all(claim.status != "unsupported" for claim in claims)
        print(f"answered in {seconds:.1f} s: {done.message.content}")
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions() as session:
            await WorkspaceService(WorkspaceRepository(session), storage).delete(user, workspace_id)
        await runner.aclose()
        await pool.close()
        await engine.dispose()
