"""Shared setup for live QA tests: ingest each benchmark corpus and gate its calibration questions.

Each corpus in `eval/data/corpora_v1.json` is uploaded to a fresh workspace on Supabase dev and
ingested with the real parser, embedder, and reranker. The first answerable calibration questions
of each corpus are retrieved and gated by S3 (strong-tier LLM), and the caller's `handle` turns
each into a result row. Workspaces are deleted afterwards. Corpora whose PDFs are missing are
skipped.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.providers.factory import Providers, build_providers, preload_models
from app.repositories.chunks import ChunkRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.storage import create_storage_from_settings
from app.services.citations import EvidenceSet
from app.services.retrieval import RetrievalOptions, RetrievalService
from app.services.sufficiency import (
    SubQuestionEvidence,
    SufficiencyGate,
    SufficiencyOptions,
    SufficiencyReport,
)
from eval import corpus
from eval.dataset import BENCHMARK, BenchmarkItem, load_items

RowT = TypeVar("RowT")
Handle = Callable[
    [BenchmarkItem, list[SubQuestionEvidence], SufficiencyReport, EvidenceSet], Awaitable[RowT]
]


def live_settings() -> Settings:
    """Settings with the real local models and Gemini; skips without a Gemini key."""
    settings = Settings().model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "reranker_provider": "cross_encoder",
            "nli_provider": "cross_encoder",
            "search_provider": "fake",
            "llm_strong_provider": "gemini",
        }
    )
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not set")
    return settings


def live_providers(settings: Settings) -> Providers:
    """Providers for `settings`, with the local models loaded."""
    providers = build_providers(settings)
    preload_models(providers)
    return providers


async def run_on_corpora(
    settings: Settings,
    providers: Providers,
    questions_per_corpus: int,
    handle: Handle[RowT],
) -> list[RowT]:
    """Ingest every available corpus and call `handle` for its first answerable questions."""
    engine = create_engine_from_settings(settings)
    if engine is None or create_storage_from_settings(settings) is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    items = [
        item
        for item in load_items(BENCHMARK, split="calibration")
        if item.answerable and item.paper
    ]
    corpora = available_corpora()
    sessions = create_sessionmaker(engine)
    gate = SufficiencyGate(providers.llm_strong, SufficiencyOptions.from_settings(settings))
    user = uuid4()

    async def corpus_rows(
        name: str, papers: list[Path], questions: list[BenchmarkItem]
    ) -> list[RowT]:
        async with corpus_workspace(settings, providers, sessions, user, name, papers) as ws:
            rows = []
            for item in questions:
                async with sessions() as session:
                    result = await RetrievalService(
                        ChunkRepository(session),
                        embedder=providers.embedder,
                        reranker=providers.reranker,
                        options=RetrievalOptions.from_settings(settings),
                    ).retrieve(user, ws, item.question)
                subs = [SubQuestionEvidence("q1", item.question, result.evidence)]
                report = await gate.assess(subs)
                rows.append(await handle(item, subs, report, EvidenceSet.build(subs, report)))
            return rows

    try:
        results: list[RowT] = []
        for name, papers in corpora.items():
            questions = [item for item in items if item.corpus == name][:questions_per_corpus]
            results.extend(await corpus_rows(name, papers, questions))
        return results
    finally:
        await engine.dispose()


def available_corpora() -> dict[str, list[Path]]:
    """Benchmark corpora whose PDFs are all present; skips the test when there are none."""
    try:
        return corpus.available_corpora()
    except corpus.CorpusUnavailableError as exc:
        pytest.skip(str(exc))


@asynccontextmanager
async def corpus_workspace(
    settings: Settings,
    providers: Providers,
    sessions: async_sessionmaker[AsyncSession],
    user: UUID,
    name: str,
    papers: list[Path],
) -> AsyncIterator[UUID]:
    """A fresh dev workspace with `papers` uploaded and ingested; deleted afterwards."""
    if create_storage_from_settings(settings) is None:
        pytest.skip("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
    async with corpus.corpus_workspace(settings, providers, sessions, user, name, papers) as ws:
        yield ws.workspace_id
