"""Retrieval quality end to end on Supabase dev (Phase 1 exit criterion: correct chunks with
page and section). Real parser, embedder, and reranker; papers are uploaded to Storage,
ingested, searched through `RetrievalService.debug`, then deleted.

Two question sets (PDFs are not committed; tests skip if they are missing):
- `scripts/data/embedding_comparison/questions.json` (16 questions, 3 arXiv papers),
- `scripts/data/embedding_check_v1.jsonl` (17 questions, papers in `scripts/data/papers/`).

Prints Recall@5, Recall@8, and MRR (snippet = the gold sentence is in the chunk; page = a chunk
of the right paper covers the gold page) and latency per question:
`uv run pytest -m integration tests/integration/test_retrieval_supabase.py -s`
With `RECORD_EXPERIMENT=1` each question set also writes an experiment JSON to docs/experiments/.
"""

import asyncio
import os
import statistics
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.main import build_ingestion
from app.providers.factory import build_providers, preload_models
from app.repositories.chunks import ChunkRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.documents import DocumentRepository
from app.repositories.storage import create_storage_from_settings
from app.repositories.topic_profiles import TopicProfileRepository
from app.repositories.workspaces import WorkspaceRepository
from app.services.documents import DocumentService
from app.services.retrieval import RetrievalOptions, RetrievalService, RetrievedChunk
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.workspaces import WorkspaceService
from scripts.compare_embeddings import Question, load_questions, normalize
from scripts.experiment_log import snippet, write_experiment

pytestmark = pytest.mark.integration

DATA = Path(__file__).resolve().parents[2] / "scripts/data"
QUESTION_SETS = {
    "embedding_comparison": (DATA / "embedding_comparison/questions.json", None),
    "embedding_check_v1": (DATA / "embedding_check_v1.jsonl", DATA / "papers"),
}
# Floors well below what task 1a measured (R@5 by page 0.94 on both sets), so the test catches
# a broken pipeline rather than small model differences.
MIN_RECALL_AT_8_PAGE = 0.8


def first_hit(
    evidence: list[RetrievedChunk], question: Question, document_id: UUID, *, by_page: bool
) -> int | None:
    """1-based rank of the first chunk that answers the question, or None."""
    snippet = normalize(question.snippet)
    for rank, chunk in enumerate(evidence, start=1):
        if chunk.document_id != document_id:
            continue
        if snippet in normalize(chunk.text) or (
            by_page and chunk.page_start <= question.page <= chunk.page_end
        ):
            return rank
    return None


def scores(ranks: list[int | None]) -> dict[str, float]:
    return {
        "R@5": sum(r is not None and r <= 5 for r in ranks) / len(ranks),
        "R@8": sum(r is not None for r in ranks) / len(ranks),
        "MRR": sum(1 / r for r in ranks if r is not None) / len(ranks),
    }


@pytest.mark.parametrize("name", list(QUESTION_SETS))
async def test_retrieval_finds_the_gold_passages(name: str) -> None:
    questions_file, papers_dir = QUESTION_SETS[name]
    if not questions_file.exists():
        pytest.skip(f"{questions_file} not found")
    papers, questions = load_questions(questions_file, papers_dir)
    if not all(path.exists() for path in papers.values()):
        pytest.skip(f"papers for {name} not found (see {questions_file.name})")
    pdfs = {paper: await asyncio.to_thread(path.read_bytes) for paper, path in papers.items()}

    settings = Settings().model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "reranker_provider": "cross_encoder",
            "search_provider": "fake",  # metadata is irrelevant here
        }
    )
    engine = create_engine_from_settings(settings)
    storage = create_storage_from_settings(settings)
    if engine is None or storage is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    providers = build_providers(settings)
    await asyncio.to_thread(preload_models, providers)
    sessions = create_sessionmaker(engine)
    ingestion = build_ingestion(settings, providers, sessions)
    user = uuid4()
    pending: list[tuple[UUID, UUID, bytes]] = []

    async with sessions() as session:
        workspace = await WorkspaceRepository(session).create(
            user,
            name=f"Integration: retrieval {name}",
            description=None,
            default_mode="corpus_only",
        )
        workspace_id = workspace.id
        await session.commit()
    try:
        documents: dict[str, UUID] = {}
        for paper, data in pdfs.items():
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
                ).upload(user, workspace_id, data)
            documents[paper] = result.document.id
        for user_id, document_id, data in pending:
            await ingestion.run(user_id, document_id, data)
        async with sessions() as session:
            repo = DocumentRepository(session)
            for paper, document_id in documents.items():
                document = await repo.get(user, document_id)
                assert document is not None and document.status == "ready", (paper, document)

        by_snippet: list[int | None] = []
        by_page: list[int | None] = []
        latencies: list[float] = []
        misses: list[str] = []
        results: list[dict[str, Any]] = []
        for question in questions:
            async with sessions() as session:
                debug = await RetrievalService(
                    ChunkRepository(session),
                    embedder=providers.embedder,
                    reranker=providers.reranker,
                    options=RetrievalOptions.from_settings(settings),
                ).debug(user, workspace_id, question.question)
            assert debug.evidence, question.question
            assert all(chunk.page_start >= 1 for chunk in debug.evidence)
            document_id = documents[question.paper]
            by_snippet.append(first_hit(debug.evidence, question, document_id, by_page=False))
            by_page.append(first_hit(debug.evidence, question, document_id, by_page=True))
            latencies.append(debug.timings.total_ms)
            top = debug.evidence[0]
            results.append(
                {
                    "paper": question.paper,
                    "question": question.question,
                    "gold_page": question.page,
                    "rank_snippet": by_snippet[-1],
                    "rank_page": by_page[-1],
                    "total_ms": debug.timings.total_ms,
                    "top_page": top.page_start,
                    "top_section": top.section and snippet(top.section),
                }
            )
            if by_page[-1] is None:
                top = debug.evidence[0]
                misses.append(f"  miss: {question.question!r} → p.{top.page_start} {top.section!r}")

        snippet_scores, page_scores = scores(by_snippet), scores(by_page)
        print(
            f"\n{name}: {len(papers)} papers, {len(questions)} questions\n"
            f"  by snippet: {fmt(snippet_scores)}\n  by page:    {fmt(page_scores)}\n"
            f"  latency per question: p50 {statistics.median(latencies):.0f} ms, "
            f"max {max(latencies):.0f} ms"
        )
        print("\n".join(misses))
        if os.environ.get("RECORD_EXPERIMENT") == "1":
            path = write_experiment(
                "retrieval_eval",
                settings=settings,
                models={
                    "embedding": providers.embedder.model_name,
                    "reranker": providers.reranker.model_name,
                    "parser": settings.parser_provider,
                },
                dataset=questions_file.name,
                parameters={"papers": len(papers), "questions": len(questions)},
                results=results,
                summary={
                    "snippet": snippet_scores,
                    "page": page_scores,
                    "latency_p50_ms": statistics.median(latencies),
                    "latency_max_ms": max(latencies),
                },
            )
            print(f"Wrote {path}")
        assert page_scores["R@8"] >= MIN_RECALL_AT_8_PAGE, page_scores
    finally:
        async with sessions() as session:
            await WorkspaceService(WorkspaceRepository(session), storage).delete(user, workspace_id)
        await engine.dispose()


def fmt(values: dict[str, float]) -> str:
    return " · ".join(f"{key} {value:.2f}" for key, value in values.items())
