"""End to end on Supabase dev: upload a real paper to Storage, ingest it with the real parser and
embedder, wait for `ready`, download it through a signed URL, then delete the workspace.

Needs DATABASE_URL, SUPABASE_URL, and SUPABASE_SECRET_KEY in backend/.env, the private
`documents` bucket, and a paper (default: the 20-page arXiv paper used by the embedding
comparison; PDFs are not committed). Prints the time to `ready` (NFR-02, local run):
`uv run pytest -m integration tests/integration/test_ingestion_supabase.py -s`
"""

import asyncio
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.main import build_ingestion
from app.models.document import Document
from app.providers.factory import build_providers, preload_models
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import DocumentRepository
from app.repositories.storage import create_storage_from_settings
from app.repositories.topic_profiles import TopicProfileRepository
from app.repositories.workspaces import WorkspaceRepository
from app.services.documents import DocumentService
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.workspaces import WorkspaceService

pytestmark = pytest.mark.integration

DEFAULT_PAPER = (
    Path(__file__).resolve().parents[2] / "scripts/data/embedding_comparison/2303.11051.pdf"
)
TIMEOUT_SECONDS = 300


def profiles(session: AsyncSession, settings: Settings) -> TopicProfileService:
    return TopicProfileService(
        TopicProfileRepository(session), CompatibilityOptions.from_settings(settings)
    )


@pytest.fixture
def paper() -> tuple[str, bytes]:
    path = Path(os.environ.get("INGESTION_TEST_PDF", DEFAULT_PAPER))
    if not path.exists():
        pytest.skip(f"{path} not found (set INGESTION_TEST_PDF)")
    return path.name, path.read_bytes()


async def test_real_paper_reaches_ready(paper: tuple[str, bytes]) -> None:
    name, data = paper
    base = Settings()
    settings = base.model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "search_provider": "live" if base.contact_email else "fake",
        }
    )
    engine = create_engine_from_settings(settings)
    storage = create_storage_from_settings(settings)
    if engine is None or storage is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    providers = build_providers(settings)
    # Deployed instances preload models at startup; leave loading out of the measurement.
    await asyncio.to_thread(preload_models, providers)
    sessions = create_sessionmaker(engine)
    ingestion = build_ingestion(settings, providers, sessions)
    user = uuid4()
    tasks: list[asyncio.Task[None]] = []

    def schedule(user_id: UUID, document_id: UUID, content: bytes) -> None:
        tasks.append(asyncio.create_task(ingestion.run(user_id, document_id, content)))

    async with sessions() as session:
        workspace = await WorkspaceRepository(session).create(
            user, name="Integration: ingestion", description=None, default_mode="corpus_only"
        )
        workspace_id = workspace.id
        await session.commit()
    try:
        started = time.perf_counter()
        async with sessions() as session:
            documents = DocumentService(
                DocumentRepository(session),
                storage,
                schedule,
                profiles=profiles(session, settings),
                signed_url_ttl_seconds=60,
            )
            result = await documents.upload(user, workspace_id, data)
        assert result.duplicate is False

        document = await wait_until_finished(sessions, user, result.document.id)
        elapsed = time.perf_counter() - started
        print(f"\n{name}: {document.page_count} pages, ready in {elapsed:.1f} s")

        assert document.status == "ready", document.error
        assert document.page_count is not None and document.page_count > 0
        async with sessions() as session:
            file_url = await DocumentService(
                DocumentRepository(session),
                storage,
                schedule,
                profiles=profiles(session, settings),
                signed_url_ttl_seconds=60,
            ).file_url(user, document.id)
        async with httpx.AsyncClient(timeout=30) as client:
            downloaded = await client.get(file_url.url)
        assert downloaded.status_code == 200
        assert downloaded.content == data
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions() as session:
            await WorkspaceService(WorkspaceRepository(session), storage).delete(user, workspace_id)
        await engine.dispose()

    with pytest.raises(ExternalServiceError):
        await storage.signed_url(f"{user}/{result.document.id}.pdf", expires_in=60)


async def wait_until_finished(
    sessions: async_sessionmaker[AsyncSession], user: UUID, document_id: UUID
) -> Document:
    """Poll the document until it is `ready` or `failed`."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        async with sessions() as session:
            document = await DocumentRepository(session).get(user, document_id)
        assert document is not None
        if document.status in ("ready", "failed"):
            return document
        assert time.monotonic() < deadline, f"still {document.status} after {TIMEOUT_SECONDS} s"
        await asyncio.sleep(0.5)
