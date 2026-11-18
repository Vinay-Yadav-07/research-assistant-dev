"""FR-04 first-page LLM metadata and the S7 keyword summary on Supabase dev (D-068).

A real paper is uploaded with the fake DOI lookup (so no DOI is confirmed and the fast-tier LLM
reads page 1), ingested with the real parser and embedder, and its workspace is summarized by the
strong-tier LLM. Needs GROQ_API_KEY, GEMINI_API_KEY, DATABASE_URL, SUPABASE_URL, and
SUPABASE_SECRET_KEY in backend/.env, and the paper (PDFs are not committed). Prints the result:
`uv run pytest -m integration tests/integration/test_metadata_keywords_live.py -s`
"""

import asyncio
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.main import build_ingestion
from app.providers.factory import build_providers, preload_models
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import DocumentRepository
from app.repositories.storage import create_storage_from_settings
from app.repositories.workspaces import WorkspaceRepository
from app.services.documents import DocumentService
from app.services.workspaces import WorkspaceService
from tests.integration.test_ingestion_supabase import (
    DEFAULT_PAPER,
    profiles,
    wait_until_finished,
)

pytestmark = pytest.mark.integration

# The arXiv paper's own title, as printed on page 1.
EXPECTED_TITLE_WORDS = {"bioceramic", "scaffolds", "hollow"}


async def test_paper_without_doi_gets_llm_metadata_and_its_workspace_keywords() -> None:
    if not DEFAULT_PAPER.exists():
        pytest.skip(f"{DEFAULT_PAPER} not found")
    settings = Settings().model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "search_provider": "fake",
            "llm_fast_provider": "groq",
            "llm_strong_provider": "gemini",
        }
    )
    if settings.groq_api_key is None or settings.gemini_api_key is None:
        pytest.skip("GROQ_API_KEY or GEMINI_API_KEY not set")
    engine = create_engine_from_settings(settings)
    storage = create_storage_from_settings(settings)
    if engine is None or storage is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    providers = build_providers(settings)
    await asyncio.to_thread(preload_models, providers)
    sessions = create_sessionmaker(engine)
    ingestion = build_ingestion(settings, providers, sessions)
    user = uuid4()
    tasks: list[asyncio.Task[None]] = []

    def schedule(user_id: UUID, document_id: UUID, content: bytes) -> None:
        tasks.append(asyncio.create_task(ingestion.run(user_id, document_id, content)))

    async with sessions() as session:
        workspace = await WorkspaceRepository(session).create(
            user, name="Integration: LLM metadata", description=None, default_mode="corpus_only"
        )
        workspace_id = workspace.id
        await session.commit()
    try:
        async with sessions() as session:
            result = await DocumentService(
                DocumentRepository(session),
                storage,
                schedule,
                profiles=profiles(session, settings),
                signed_url_ttl_seconds=60,
            ).upload(user, workspace_id, DEFAULT_PAPER.read_bytes())
        document = await wait_until_finished(sessions, user, result.document.id)
        # `run` refreshes the workspace summary after the document is ready.
        await asyncio.gather(*tasks)
        async with sessions() as session:
            summarized = await WorkspaceRepository(session).get(user, workspace_id)

        print(f"\ntitle:    {document.title}\nauthors:  {document.authors}")
        print(f"year:     {document.year}   venue: {document.venue}   doi: {document.doi}")
        assert summarized is not None
        print(f"keywords: {summarized.keywords}\nsummary:  {summarized.summary}")

        assert document.status == "ready", document.error
        assert document.doi is None
        assert document.title is not None
        assert set(document.title.lower().split()) >= EXPECTED_TITLE_WORDS
        assert document.authors
        assert summarized.keywords and summarized.summary
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions() as session:
            await WorkspaceService(WorkspaceRepository(session), storage).delete(user, workspace_id)
        await engine.dispose()
