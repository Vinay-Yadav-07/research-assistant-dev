"""The eval runner end to end with fakes: conditions, scoring, the result sink, the report."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ragas.metrics.collections.answer_relevancy.util import AnswerRelevanceOutput

from app.core.errors import LLMProviderError
from app.providers.fakes import FakeEmbedder, FakeLLM
from app.services.retrieval import RetrievalResult
from eval.conditions import BaselineAnswer, Retrieve
from eval.corpus import CorpusWorkspace
from eval.dataset import GoldPassage
from eval.judge import RagasScorer
from eval.report import markdown_report
from eval.run import evaluate, main, parse_args, select_items
from tests.unit.eval.helpers import chunk, item

PAPER = uuid4()
USER = uuid4()


class MemorySink:
    def __init__(self) -> None:
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.results: list[tuple[UUID, str, dict[str, Any], dict[str, Any]]] = []

    async def create_run(
        self, condition: str, config: dict[str, Any], dataset_version: str
    ) -> UUID:
        run_id = uuid4()
        self.runs[run_id] = {"condition": condition, "config": config, "dataset": dataset_version}
        return run_id

    async def add_result(
        self, run_id: UUID, question_id: str, output: dict[str, Any], scores: dict[str, Any]
    ) -> None:
        self.results.append((run_id, question_id, output, scores))

    async def finish_run(self, run_id: UUID, metrics: dict[str, Any]) -> None:
        self.runs[run_id]["metrics"] = metrics


def answer(text: str, abstained: bool = False) -> BaselineAnswer:
    return BaselineAnswer(answer=text, abstained=abstained)


async def test_c1_runs_every_item_without_a_workspace() -> None:
    items = [item("t1"), item("t2", type_="unanswerable", corpus="scaffolds")]
    llm = FakeLLM(structured={BaselineAnswer: [answer("A."), answer("Unknown.", True)]})
    sink = MemorySink()

    results, summary = await evaluate("C1", items, llm=llm, config={"c": 1}, sink=sink)

    assert [r.output.answer for r in results if r.output] == ["A.", "Unknown."]
    assert all(r.retrieval is None and r.usage.calls == 1 for r in results)
    assert summary["verified"] is None
    assert summary["all"]["abstention"]["abstention_accuracy"] == 1.0
    [run] = sink.runs.values()
    assert (run["condition"], run["config"], run["dataset"]) == ("C1", {"c": 1}, "benchmark_v1")
    assert run["metrics"] == summary
    assert [question for _, question, _, _ in sink.results] == ["t1", "t2"]


async def test_c2_opens_one_workspace_per_corpus_and_scores_retrieval() -> None:
    items = [
        item("t1", gold=(GoldPassage("a.pdf", 3, "porosity was 84%"),)),
        item("t2", type_="unanswerable"),
        item("t3", corpus="scaffolds", gold=(GoldPassage("a.pdf", 9, "not retrieved"),)),
    ]
    opened: list[str] = []
    asked: list[tuple[str, str]] = []

    @asynccontextmanager
    async def open_workspace(name: str) -> AsyncIterator[CorpusWorkspace]:
        opened.append(name)
        yield CorpusWorkspace(USER, uuid4(), {"a.pdf": PAPER})

    def retriever_for(workspace: CorpusWorkspace) -> Retrieve:
        async def retrieve(question: str) -> RetrievalResult:
            asked.append((str(workspace.workspace_id), question))
            evidence = [chunk("noise"), chunk("Porosity was 84%.", document_id=PAPER, page=3)]
            return RetrievalResult(query=question, evidence=evidence)

        return retrieve

    llm = FakeLLM(structured={BaselineAnswer: [answer("84%."), answer("No.", True), answer("?")]})

    results, summary = await evaluate(
        "C2",
        items,
        llm=llm,
        config={},
        open_workspace=open_workspace,
        retriever_for=retriever_for,
    )

    assert opened == ["tissue", "scaffolds"]
    assert len({workspace for workspace, _ in asked}) == 2
    t1, t2, t3 = results
    assert t1.retrieval is not None and t1.retrieval.snippet_ranks == [2]
    assert t2.retrieval is None
    assert t3.retrieval is not None and t3.retrieval.page_ranks == [None]
    assert summary["all"]["retrieval"]["snippet"]["R@8"] == 0.5
    assert summary["all"]["retrieval"]["snippet"]["MRR"] == 0.25


async def test_c2_needs_a_workspace_and_retriever() -> None:
    with pytest.raises(ValueError, match="C2 needs"):
        await evaluate("C2", [item()], llm=FakeLLM(), config={})


async def test_failures_are_recorded_and_the_run_goes_on() -> None:
    items = [item("t1"), item("t2")]
    llm = FakeLLM(structured={BaselineAnswer: [LLMProviderError(), answer("A.")]})
    sink = MemorySink()

    results, summary = await evaluate("C1", items, llm=llm, config={}, sink=sink)

    assert results[0].output is None and results[0].error is not None
    assert results[0].error.startswith("LLMProviderError")
    assert results[1].output is not None
    assert summary["all"]["failed"] == 1
    assert sink.results[0][2]["error"] == results[0].error


async def test_ragas_scores_answers_but_not_abstentions() -> None:
    items = [item("t1", verified_by="reviewer"), item("t2", type_="unanswerable")]
    llm = FakeLLM(structured={BaselineAnswer: [answer("Fibrinogen."), answer("No.", True)]})
    judge = FakeLLM(structured={AnswerRelevanceOutput: [{"question": "Q?", "noncommittal": 0}]})
    scorer = RagasScorer(judge, FakeEmbedder(dimension=32), strictness=1)

    results, summary = await evaluate("C1", items, llm=llm, config={}, scorer=scorer)

    assert results[0].ragas is not None and results[0].ragas.faithfulness is None
    assert results[0].judge_usage.calls == 1
    assert results[1].ragas is None and results[1].judge_usage.calls == 0
    assert summary["verified"]["questions"] == 1
    assert summary["all"]["ragas"]["answer_relevancy_scored"] == 1


async def test_judge_errors_do_not_fail_the_question() -> None:
    llm = FakeLLM(structured={BaselineAnswer: [answer("A.")]})
    judge = FakeLLM(structured={AnswerRelevanceOutput: [LLMProviderError()]})
    scorer = RagasScorer(judge, FakeEmbedder(dimension=32), strictness=1)

    [result], summary = await evaluate("C1", [item()], llm=llm, config={}, scorer=scorer)

    assert result.output is not None and result.ragas is None
    assert result.judge_error is not None
    assert summary["all"]["ragas"]["judge_errors"] == 1


def test_items_are_selected_per_corpus() -> None:
    test = select_items("test", limit=None, corpora=None)
    limited = select_items("test", limit=2, corpora=None)
    tissue = select_items("test", limit=None, corpora=["tissue"])

    assert len(test) >= 50
    assert [i.corpus for i in limited] == ["tissue", "tissue", "scaffolds", "scaffolds"]
    assert tissue and {i.corpus for i in tissue} == {"tissue"}


def test_cli_options() -> None:
    args = parse_args(["--condition", "C2", "--limit", "3", "--no-ragas", "--corpus", "tissue"])
    assert (args.condition, args.split, args.limit, args.ragas, args.corpus) == (
        "C2",
        "test",
        3,
        False,
        ["tissue"],
    )
    assert parse_args(["--condition", "C1"]).ragas
    with pytest.raises(SystemExit):
        parse_args(["--condition", "C5"])


async def test_markdown_report_covers_verified_and_all_items() -> None:
    llm = FakeLLM(structured={BaselineAnswer: [answer("A."), answer("No.", True)]})
    items = [item("t1"), item("t2", type_="unanswerable")]
    _, summary = await evaluate("C1", items, llm=llm, config={})
    config = {
        "condition": "C1",
        "split": "test",
        "generation_model": "fake-llm",
        "prompt_version": "v1",
        "retrieval": None,
        "ragas": False,
    }

    report = markdown_report(config, summary)

    assert report.startswith("# C1 on the test split\n")
    assert "No verified items yet" in report
    assert "| Abstention accuracy (unanswerable) | 1.000 (1/1) |" in report
    assert "Retrieval by page" not in report
    assert "- Ragas judge: off" in report


async def test_c2_refuses_a_fake_fast_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ingestion extracts paper metadata with the fast tier; a fake one fails every paper.
    monkeypatch.setenv("LLM_STRONG_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_FAST_PROVIDER", "fake")

    with pytest.raises(SystemExit, match="LLM_FAST_PROVIDER"):
        await main(parse_args(["--condition", "C2", "--no-ragas"]))


async def test_a_fake_strong_tier_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_STRONG_PROVIDER", "fake")

    with pytest.raises(SystemExit, match="LLM_STRONG_PROVIDER"):
        await main(parse_args(["--condition", "C1", "--no-ragas"]))


async def test_an_empty_retrieval_counts_as_a_miss() -> None:
    @asynccontextmanager
    async def open_workspace(name: str) -> AsyncIterator[CorpusWorkspace]:
        yield CorpusWorkspace(USER, uuid4(), {"a.pdf": PAPER})

    def retriever_for(workspace: CorpusWorkspace) -> Retrieve:
        async def retrieve(question: str) -> RetrievalResult:
            return RetrievalResult(query=question, evidence=[])

        return retrieve

    llm = FakeLLM(structured={BaselineAnswer: [answer("No.", True)]})

    [result], summary = await evaluate(
        "C2",
        [item()],
        llm=llm,
        config={},
        open_workspace=open_workspace,
        retriever_for=retriever_for,
    )

    assert result.retrieval is not None and result.retrieval.page_ranks == [None]
    assert summary["all"]["retrieval"]["page"]["R@8"] == 0.0
