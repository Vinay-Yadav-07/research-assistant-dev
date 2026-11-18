"""Benchmark corpora in a real workspace: upload each corpus's PDFs and ingest them.

Used by the eval runner and the live integration tests. Needs Supabase (database and Storage)
and the real parser and embedder in `settings`; the PDFs are git-ignored and may be missing.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.main import build_ingestion
from app.providers.factory import Providers
from app.repositories.documents import DocumentRepository
from app.repositories.storage import create_storage_from_settings
from app.repositories.topic_profiles import TopicProfileRepository
from app.repositories.workspaces import WorkspaceRepository
from app.services.documents import DocumentService
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.workspaces import WorkspaceService
from eval.dataset import load_corpora


class CorpusUnavailableError(RuntimeError):
    """A corpus cannot be set up: PDFs, Storage settings, or ingestion are missing or failed."""


@dataclass(frozen=True)
class CorpusWorkspace:
    """A user's workspace holding one corpus, and the document id of each paper file name."""

    user_id: UUID
    workspace_id: UUID
    documents: dict[str, UUID]


def available_corpora() -> dict[str, list[Path]]:
    """Benchmark corpora whose PDFs are all present; raises if there are none."""
    corpora = {
        name: papers
        for name, papers in load_corpora().items()
        if all(path.exists() for path in papers)
    }
    if not corpora:
        raise CorpusUnavailableError("no corpus has all its PDFs (see eval/data/corpora_v1.json)")
    return corpora


@asynccontextmanager
async def corpus_workspace(
    settings: Settings,
    providers: Providers,
    sessions: async_sessionmaker[AsyncSession],
    user: UUID,
    name: str,
    papers: list[Path],
) -> AsyncIterator[CorpusWorkspace]:
    """A fresh workspace with `papers` uploaded and ingested; deleted afterwards.

    Raises `CorpusUnavailableError` if Storage is not configured or a paper is not `ready`.
    """
    storage = create_storage_from_settings(settings)
    if storage is None:
        raise CorpusUnavailableError("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
    ingestion = build_ingestion(settings, providers, sessions)
    async with sessions() as session:
        workspace = await WorkspaceRepository(session).create(
            user, name=f"Eval: {name}", description=None, default_mode="corpus_only"
        )
        await session.commit()
    pending: list[tuple[UUID, UUID, bytes]] = []
    documents: dict[str, UUID] = {}
    try:
        for path in papers:
            data = await asyncio.to_thread(path.read_bytes)
            async with sessions() as session:
                result = await DocumentService(
                    DocumentRepository(session),
                    storage,
                    lambda u, d, b: pending.append((u, d, b)),
                    profiles=TopicProfileService(
                        TopicProfileRepository(session),
                        CompatibilityOptions.from_settings(settings),
                    ),
                    signed_url_ttl_seconds=60,
                ).upload(user, workspace.id, data, override=True)
            documents[path.name] = result.document.id
        for user_id, document_id, data in pending:
            await ingestion.run(user_id, document_id, data)
        async with sessions() as session:
            repo = DocumentRepository(session)
            for paper, document_id in documents.items():
                document = await repo.get(user, document_id)
                if document is None or document.status != "ready":
                    raise CorpusUnavailableError(f"{paper} did not reach status 'ready'")
        yield CorpusWorkspace(user, workspace.id, documents)
    finally:
        async with sessions() as session:
            await WorkspaceService(WorkspaceRepository(session), storage).delete(user, workspace.id)
