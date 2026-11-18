"""S3 gate calibration on Supabase dev (FR-10, D-063, D-065): benchmark v1 calibration split.

Each corpus in `eval/data/corpora_v1.json` is uploaded to a fresh workspace and ingested with the
real parser, embedder, and reranker; every calibration question of that corpus is retrieved and
gated as one sub-question with the real strong-tier LLM (needs GEMINI_API_KEY). Prints false
abstentions first (answerable judged insufficient), then unanswerable questions judged covered or
partial, each with the model's reason:
`uv run pytest -m integration tests/integration/test_sufficiency_supabase.py -s`
With `RECORD_EXPERIMENT=1` it also writes an experiment JSON to docs/experiments/.
Corpora whose PDFs are missing are skipped.
"""

import asyncio
import os
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
from app.services.retrieval import RetrievalOptions, RetrievalService
from app.services.sufficiency import SubQuestionEvidence, SufficiencyGate, SufficiencyOptions
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from app.services.workspaces import WorkspaceService
from eval.dataset import BENCHMARK, BenchmarkItem, load_corpora, load_items
from scripts.calibrate_sufficiency import GateOutcome, summarize
from scripts.experiment_log import snippet, write_experiment

pytestmark = pytest.mark.integration

# Target from the team: at most this many answerable calibration questions judged insufficient.
MAX_FALSE_INSUFFICIENT = 2


async def test_sufficiency_threshold_separates_answerable_questions() -> None:
    settings = Settings().model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "reranker_provider": "cross_encoder",
            "search_provider": "fake",
            "llm_strong_provider": "gemini",
        }
    )
    if settings.gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not set")
    engine = create_engine_from_settings(settings)
    storage = create_storage_from_settings(settings)
    if engine is None or storage is None:
        pytest.skip("DATABASE_URL, SUPABASE_URL, or SUPABASE_SECRET_KEY is not set")
    items = load_items(BENCHMARK, split="calibration")
    corpora = {
        name: papers
        for name, papers in load_corpora().items()
        if all(path.exists() for path in papers)
    }
    if not corpora:
        pytest.skip("no corpus has all its PDFs (see eval/data/corpora_v1.json)")
    providers = build_providers(settings)
    await asyncio.to_thread(preload_models, providers)
    sessions = create_sessionmaker(engine)
    ingestion = build_ingestion(settings, providers, sessions)
    gate = SufficiencyGate(providers.llm_strong, SufficiencyOptions.from_settings(settings))
    user = uuid4()

    async def top_scores(name: str, papers: list[Path], questions: list[BenchmarkItem]) -> Any:
        async with sessions() as session:
            workspace = await WorkspaceRepository(session).create(
                user,
                name=f"Integration: sufficiency {name}",
                description=None,
                default_mode="corpus_only",
            )
            await session.commit()
        pending: list[tuple[UUID, UUID, bytes]] = []
        try:
            for path in papers:
                data = await asyncio.to_thread(path.read_bytes)
                async with sessions() as session:
                    await DocumentService(
                        DocumentRepository(session),
                        storage,
                        lambda u, d, b: pending.append((u, d, b)),
                        profiles=TopicProfileService(
                            TopicProfileRepository(session),
                            CompatibilityOptions.from_settings(settings),
                        ),
                        signed_url_ttl_seconds=60,
                    ).upload(user, workspace.id, data, override=True)
            for user_id, document_id, data in pending:
                await ingestion.run(user_id, document_id, data)
            rows = []
            for item in questions:
                async with sessions() as session:
                    result = await RetrievalService(
                        ChunkRepository(session),
                        embedder=providers.embedder,
                        reranker=providers.reranker,
                        options=RetrievalOptions.from_settings(settings),
                    ).retrieve(user, workspace.id, item.question)
                report = await gate.assess(
                    [SubQuestionEvidence(item.id, item.question, result.evidence)]
                )
                decision = report.sub_questions[0]
                top = result.evidence[0] if result.evidence else None
                rows.append(
                    {
                        "id": item.id,
                        "corpus": name,
                        "question": item.question,
                        "answerable": item.answerable,
                        "top_score": decision.top_score,
                        "coverage": decision.coverage,
                        "decided_by": decision.decided_by,
                        "reason": decision.reason,
                        "top_page": top and top.page_start,
                        "top_text": top and snippet(top.text),
                    }
                )
            return rows
        finally:
            async with sessions() as session:
                await WorkspaceService(WorkspaceRepository(session), storage).delete(
                    user, workspace.id
                )

    try:
        results: list[dict[str, Any]] = []
        for name, papers in corpora.items():
            questions = [item for item in items if item.corpus == name]
            results.extend(await top_scores(name, papers, questions))
    finally:
        await engine.dispose()

    outcomes = [
        GateOutcome(
            row["id"],
            row["question"],
            row["answerable"],
            row["top_score"],
            row["coverage"],
            row["decided_by"],
            row["reason"],
        )
        for row in results
    ]
    summary = summarize(outcomes, fast_pass_score=settings.sufficiency_fast_pass_score)
    used = [item for item in items if item.corpus in corpora]
    verified = sum(bool(item.verified_by) for item in used)
    print(
        f"\nS3 calibration: corpora {sorted(corpora)}, {summary.answerable} answerable, "
        f"{summary.unanswerable} unanswerable ({verified} of {len(used)} human-verified), "
        f"model {providers.llm_strong.model_name}, fast pass "
        f"{settings.sufficiency_fast_pass_score}\n"
        f"  1. answerable judged insufficient: {len(summary.false_insufficient)} of "
        f"{summary.answerable} (target 0-2)\n"
        f"  2. unanswerable judged covered: {len(summary.false_covered)} of "
        f"{summary.unanswerable}; judged partial: {len(summary.false_partial)}\n"
        f"  fast-passed answerable: {summary.answerable_fast_passed}; LLM-checked: "
        f"{summary.llm_checked}; highest unanswerable score {summary.max_unanswerable_score:.3f}"
    )
    for title, wrong in (
        ("answerable judged insufficient", summary.false_insufficient),
        ("unanswerable judged covered", summary.false_covered),
        ("unanswerable judged partial", summary.false_partial),
    ):
        for o in wrong:
            print(f"  [{title}] {o.id} ({o.top_score or 0:.3f}) {o.question}\n      → {o.reason}")
    if os.environ.get("RECORD_EXPERIMENT") == "1":
        path = write_experiment(
            "calibrate_sufficiency",
            settings=settings,
            models={
                "embedding": providers.embedder.model_name,
                "reranker": providers.reranker.model_name,
                "llm_strong": providers.llm_strong.model_name,
                "parser": settings.parser_provider,
            },
            dataset=f"{BENCHMARK.name} (calibration split)",
            parameters={
                "corpora": sorted(corpora),
                "prompt": "sufficiency_check.v1",
                "human_verified": verified,
            },
            results=results,
            summary={
                "answerable": summary.answerable,
                "unanswerable": summary.unanswerable,
                "false_insufficient": [o.id for o in summary.false_insufficient],
                "false_covered": [o.id for o in summary.false_covered],
                "false_partial": [o.id for o in summary.false_partial],
                "llm_checked": summary.llm_checked,
                "answerable_fast_passed": summary.answerable_fast_passed,
                "max_unanswerable_score": summary.max_unanswerable_score,
            },
        )
        print(f"Wrote {path}")
    assert len(summary.false_insufficient) <= MAX_FALSE_INSUFFICIENT, summary.false_insufficient
