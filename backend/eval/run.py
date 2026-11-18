"""Evaluation CLI (FR-27, SRS §17): run one condition on a benchmark split and report it.

Run from `backend/` with the `eval` dependency group. C1 and C2 answer with the strong tier;
C2 also needs Supabase dev, the corpus PDFs (`eval/data/corpora_v1.json`), and a real fast tier
(ingestion extracts paper metadata with it); Ragas needs the judge (`EVAL_JUDGE_*`):
    uv run --group eval python -m eval.run --condition C1
    uv run --group eval python -m eval.run --condition C2 --limit 3 --no-ragas

Each corpus is uploaded and ingested into a fresh workspace (deleted afterwards). Every
question's output and scores go to `eval_results` as they finish, the summary to `eval_runs`,
and the report to `eval/reports/<UTC time>_eval_<condition>_<split>_<sha7>.json` plus a
Markdown table next to it. Results are reported on the test split (D-063); metrics are given
for verified items and for all items, with the drafted/verified counts.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import configure_logging
from app.providers.factory import Providers, build_providers, preload_models
from app.providers.llm import LLMProvider
from app.providers.usage import track_usage
from app.repositories.chunks import ChunkRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.eval_runs import EvalRunRepository
from app.services.retrieval import RetrievalOptions, RetrievalResult, RetrievalService
from eval import corpus
from eval.conditions import Condition, ConventionalRAG, LLMOnly, Retrieve
from eval.conditions.c1_llm_only import PROMPT_VERSION as C1_PROMPT
from eval.conditions.c2_conventional_rag import PROMPT_VERSION as C2_PROMPT
from eval.dataset import DATASET_VERSION, BenchmarkItem, Split, load_items
from eval.judge import RagasScorer, build_judge
from eval.metrics import ItemResult, score_retrieval, summarize
from eval.report import markdown_report
from scripts.experiment_log import write_experiment

logger = logging.getLogger("eval")

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
ConditionName = Literal["C1", "C2"]
CONDITIONS: tuple[ConditionName, ...] = ("C1", "C2")

# The workspace holding one corpus, opened for the questions about that corpus.
OpenWorkspace = Callable[[str], AbstractAsyncContextManager[corpus.CorpusWorkspace]]
# Dense retrieval bound to one corpus workspace.
RetrieverFor = Callable[[corpus.CorpusWorkspace], Retrieve]


class ResultSink(Protocol):
    """Where a run and its results are stored as they finish (`eval_runs`/`eval_results`)."""

    async def create_run(
        self, condition: str, config: dict[str, Any], dataset_version: str
    ) -> UUID: ...

    async def add_result(
        self, run_id: UUID, question_id: str, output: dict[str, Any], scores: dict[str, Any]
    ) -> None: ...

    async def finish_run(self, run_id: UUID, metrics: dict[str, Any]) -> None: ...


class DatabaseSink:
    """`ResultSink` over `EvalRunRepository`, one session per write."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_run(
        self, condition: str, config: dict[str, Any], dataset_version: str
    ) -> UUID:
        async with self._sessions() as session:
            return await EvalRunRepository(session).create_run(condition, config, dataset_version)

    async def add_result(
        self, run_id: UUID, question_id: str, output: dict[str, Any], scores: dict[str, Any]
    ) -> None:
        async with self._sessions() as session:
            await EvalRunRepository(session).add_result(run_id, question_id, output, scores)

    async def finish_run(self, run_id: UUID, metrics: dict[str, Any]) -> None:
        async with self._sessions() as session:
            await EvalRunRepository(session).finish_run(run_id, metrics)


def build_condition(name: ConditionName, llm: LLMProvider, retrieve: Retrieve | None) -> Condition:
    """The condition `name`; C2 needs a retriever."""
    if name == "C1":
        return LLMOnly(llm)
    if retrieve is None:
        raise ValueError("C2 needs a retriever")
    return ConventionalRAG(llm, retrieve)


async def evaluate(
    condition: ConditionName,
    items: Sequence[BenchmarkItem],
    *,
    llm: LLMProvider,
    config: dict[str, Any],
    open_workspace: OpenWorkspace | None = None,
    retriever_for: RetrieverFor | None = None,
    scorer: RagasScorer | None = None,
    sink: ResultSink | None = None,
) -> tuple[list[ItemResult], dict[str, Any]]:
    """Answer and score every item, corpus by corpus; returns the results and the summary.

    C2 opens each corpus's workspace with `open_workspace` and retrieves with
    `retriever_for(workspace)`. A failed answer or judgment is recorded and the run goes on.
    """
    needs_workspace = condition == "C2"
    if needs_workspace and (open_workspace is None or retriever_for is None):
        raise ValueError("C2 needs open_workspace and retriever_for")
    run_id = await sink.create_run(condition, config, DATASET_VERSION) if sink else None
    results: list[ItemResult] = []
    for corpus_name in dict.fromkeys(item.corpus for item in items):
        questions = [item for item in items if item.corpus == corpus_name]
        workspace_cm: AbstractAsyncContextManager[corpus.CorpusWorkspace | None] = (
            open_workspace(corpus_name)
            if needs_workspace and open_workspace is not None
            else nullcontext(None)
        )
        async with workspace_cm as workspace:
            retrieve = retriever_for(workspace) if retriever_for and workspace else None
            documents = workspace.documents if workspace else {}
            runner = build_condition(condition, llm, retrieve)
            for item in questions:
                result = await _run_item(runner, item, documents, scorer)
                results.append(result)
                logger.info("%s %s: %s", condition, item.id, _outcome(result))
                if sink and run_id:
                    await sink.add_result(run_id, item.id, *_result_record(result))
    summary = summary_for(results)
    if sink and run_id:
        await sink.finish_run(run_id, summary)
    return results, summary


def summary_for(results: Sequence[ItemResult]) -> dict[str, Any]:
    """Metrics over verified items and over all items (D-063)."""
    verified = [r for r in results if r.item.verified]
    return {"verified": summarize(verified) if verified else None, "all": summarize(results)}


async def _run_item(
    condition: Condition,
    item: BenchmarkItem,
    documents: dict[str, UUID],
    scorer: RagasScorer | None,
) -> ItemResult:
    started = time.perf_counter()
    with track_usage() as usage:
        try:
            output = await condition.run(item.question)
            error = None
        except Exception as exc:
            output, error = None, f"{type(exc).__name__}: {exc}"
    result = ItemResult(
        item=item,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        usage=usage,
        output=output,
        error=error,
    )
    if output is None:
        return result
    # A retrieval condition always sets retrieval_ms; an empty retrieval counts as a miss.
    if output.retrieval_ms is not None and item.gold:
        result.retrieval = score_retrieval(item.gold, output.contexts, documents)
    if scorer is not None and not output.abstained and output.answer.strip():
        with track_usage() as judge_usage:
            try:
                result.ragas = await scorer.score(
                    item.question, output.answer, [chunk.text for chunk in output.contexts]
                )
            except Exception as exc:
                result.judge_error = f"{type(exc).__name__}: {exc}"
        result.judge_usage = judge_usage
    return result


def _outcome(result: ItemResult) -> str:
    if result.output is None:
        return f"failed ({result.error})"
    return "abstained" if result.output.abstained else "answered"


def _report_row(result: ItemResult) -> dict[str, Any]:
    output, scores = _result_record(result)
    return {"id": result.item.id, "output": output, "scores": scores}


def _result_record(result: ItemResult) -> tuple[dict[str, Any], dict[str, Any]]:
    """(output, scores) of one result, as stored in `eval_results` and the report."""
    output = result.output
    contexts = output.contexts if output else []
    record = {
        "question": result.item.question,
        "answer": output.answer if output else None,
        "abstained": output.abstained if output else None,
        "error": result.error,
        "contexts": [
            {
                "chunk_id": str(c.chunk_id),
                "document_id": str(c.document_id),
                "page_start": c.page_start,
                "page_end": c.page_end,
                "dense_rank": c.dense_rank,
            }
            for c in contexts
        ],
    }
    retrieval = result.retrieval
    scores = {
        "type": result.item.type,
        "answerable": result.item.answerable,
        "verified": result.item.verified,
        "latency_ms": result.latency_ms,
        "retrieval_ms": output.retrieval_ms if output else None,
        "llm_calls": result.usage.calls,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "snippet_ranks": retrieval.snippet_ranks if retrieval else None,
        "page_ranks": retrieval.page_ranks if retrieval else None,
        "faithfulness": result.ragas.faithfulness if result.ragas else None,
        "answer_relevancy": result.ragas.answer_relevancy if result.ragas else None,
        "judge_calls": result.judge_usage.calls,
        "judge_error": result.judge_error,
    }
    return record, scores


# --- CLI ---


def eval_settings() -> Settings:
    """Settings from the environment with the real parser and embedder (as in production)."""
    return Settings().model_copy(
        update={
            "parser_provider": "pymupdf4llm",
            "embedding_provider": "sentence_transformers",
            "search_provider": "fake",
        }
    )


def select_items(
    split: Split, *, limit: int | None, corpora: Sequence[str] | None
) -> list[BenchmarkItem]:
    """The split's items, optionally only some corpora and the first `limit` of each corpus."""
    items = [i for i in load_items(split=split) if corpora is None or i.corpus in corpora]
    if limit is None:
        return items
    kept: list[BenchmarkItem] = []
    for name in dict.fromkeys(item.corpus for item in items):
        kept.extend([item for item in items if item.corpus == name][:limit])
    return kept


async def main(args: argparse.Namespace) -> Path:
    """Run the CLI; returns the report path."""
    settings = eval_settings()
    if settings.llm_strong_provider in ("fake", "demo"):
        raise SystemExit("Set LLM_STRONG_PROVIDER (the model C1/C2 answer with) to a real LLM.")
    if args.condition == "C2" and settings.llm_fast_provider in ("fake", "demo"):
        raise SystemExit("Set LLM_FAST_PROVIDER to a real LLM (ingestion reads paper metadata).")
    if args.ragas and settings.eval_judge_provider == "fake":
        raise SystemExit("Set EVAL_JUDGE_PROVIDER (or pass --no-ragas).")
    condition: ConditionName = args.condition
    items = select_items(args.split, limit=args.limit, corpora=args.corpus)
    if not items:
        raise SystemExit("No benchmark items selected.")
    providers = build_providers(settings)
    await asyncio.to_thread(preload_models, providers)
    scorer = (
        RagasScorer(
            build_judge(settings),
            providers.embedder,
            strictness=settings.eval_answer_relevancy_strictness,
        )
        if args.ragas
        else None
    )
    engine = create_engine_from_settings(settings)
    if engine is None and condition == "C2":
        raise SystemExit("C2 needs DATABASE_URL (the corpora are ingested on Supabase dev).")
    sessions = create_sessionmaker(engine) if engine is not None else None
    config = run_config(settings, providers, condition, args, len(items))
    try:
        results, summary = await evaluate(
            condition,
            items,
            llm=providers.llm_strong,
            config=config,
            open_workspace=_workspace_opener(settings, providers, sessions),
            retriever_for=_retriever(settings, providers, sessions),
            scorer=scorer,
            sink=DatabaseSink(sessions) if sessions is not None else None,
        )
    finally:
        if engine is not None:
            await engine.dispose()
    path = write_experiment(
        f"eval_{condition}_{args.split}",
        settings=settings,
        models={"generation": providers.llm_strong.model_name, "judge": config["judge_model"]},
        dataset=f"{DATASET_VERSION} ({args.split} split)",
        results=[_report_row(result) for result in results],
        summary=summary,
        parameters=config,
        directory=REPORTS_DIR,
    )
    path.with_suffix(".md").write_text(markdown_report(config, summary), encoding="utf-8")
    return path


def run_config(
    settings: Settings,
    providers: Providers,
    condition: ConditionName,
    args: argparse.Namespace,
    item_count: int,
) -> dict[str, Any]:
    """What makes a run reproducible, stored with it."""
    return {
        "condition": condition,
        "split": args.split,
        "limit": args.limit,
        "corpora": args.corpus,
        "items": item_count,
        "generation_model": providers.llm_strong.model_name,
        "prompt_version": C1_PROMPT if condition == "C1" else C2_PROMPT,
        "retrieval": "dense" if condition == "C2" else None,
        "top_k": settings.retrieval_top_k if condition == "C2" else None,
        "embedding_model": settings.embedding_model if condition == "C2" else None,
        "ragas": args.ragas,
        "judge_model": settings.eval_judge_model if args.ragas else None,
        "answer_relevancy_strictness": (
            settings.eval_answer_relevancy_strictness if args.ragas else None
        ),
    }


def _workspace_opener(
    settings: Settings,
    providers: Providers,
    sessions: async_sessionmaker[AsyncSession] | None,
) -> OpenWorkspace | None:
    if sessions is None:
        return None
    bound_sessions = sessions
    available = corpus.available_corpora()
    user = uuid4()

    def open_workspace(name: str) -> AbstractAsyncContextManager[corpus.CorpusWorkspace]:
        if name not in available:
            raise corpus.CorpusUnavailableError(f"corpus {name!r} has missing PDFs")
        logger.info("Ingesting corpus %r (%d papers)", name, len(available[name]))
        return corpus.corpus_workspace(
            settings, providers, bound_sessions, user, name, available[name]
        )

    return open_workspace


def _retriever(
    settings: Settings, providers: Providers, sessions: async_sessionmaker[AsyncSession] | None
) -> RetrieverFor | None:
    if sessions is None:
        return None
    bound_sessions = sessions
    options = RetrievalOptions.from_settings(settings)

    def retriever_for(workspace: corpus.CorpusWorkspace) -> Retrieve:
        async def retrieve(question: str) -> RetrievalResult:
            async with bound_sessions() as session:
                service = RetrievalService(
                    ChunkRepository(session),
                    embedder=providers.embedder,
                    reranker=providers.reranker,
                    options=options,
                )
                return await service.retrieve_dense(
                    workspace.user_id, workspace.workspace_id, question
                )

        return retrieve

    return retriever_for


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__.split("\n")[0])
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    parser.add_argument("--split", choices=("test", "calibration"), default="test")
    parser.add_argument("--limit", type=int, help="first N items of each corpus")
    parser.add_argument("--corpus", action="append", help="only this corpus (repeatable)")
    parser.add_argument("--no-ragas", dest="ragas", action="store_false")
    return parser.parse_args(argv)


if __name__ == "__main__":
    configure_logging()
    report = asyncio.run(main(parse_args()))
    print(f"Report: {report}")
