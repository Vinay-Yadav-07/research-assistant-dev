"""Benchmark metrics (SRS §17.3): gold hits, Recall@K/MRR, abstention, Ragas, system."""

from uuid import uuid4

import pytest

from app.providers.usage import RunUsage
from eval.conditions import ConditionOutput
from eval.dataset import GoldPassage
from eval.judge import RagasScores
from eval.metrics import ItemResult, RetrievalScores, hits, normalize, score_retrieval, summarize
from tests.unit.eval.helpers import chunk, item

PAPER_A, PAPER_B = uuid4(), uuid4()
DOCUMENTS = {"a.pdf": PAPER_A, "b.pdf": PAPER_B}
GOLD = GoldPassage("a.pdf", 3, "Porosity was ~84%")


def test_normalize_ignores_case_markdown_and_hyphenation() -> None:
    assert normalize("**Porosity** was ~84 %,\nnot-bad") == "porosity was 84 not bad"


def test_snippet_hit_needs_the_gold_paper() -> None:
    text = "In the sintered state, porosity was 84% for hollow struts."
    assert hits(chunk(text, document_id=PAPER_A, page=9), GOLD, DOCUMENTS, by_page=False)
    assert not hits(chunk(text, document_id=PAPER_B, page=3), GOLD, DOCUMENTS, by_page=True)


def test_page_hit_needs_the_page_in_the_chunk_range() -> None:
    other_text = chunk("Unrelated.", document_id=PAPER_A, page=2, end=4)
    assert hits(other_text, GOLD, DOCUMENTS, by_page=True)
    assert not hits(other_text, GOLD, DOCUMENTS, by_page=False)
    assert not hits(chunk("x", document_id=PAPER_A, page=4), GOLD, DOCUMENTS, by_page=True)


def test_ranks_recall_and_reciprocal_rank() -> None:
    second = GoldPassage("b.pdf", 7, "stiffness rose")
    contexts = [
        chunk("noise", document_id=PAPER_B, page=1),
        chunk("Same page, other text.", document_id=PAPER_A, page=3),
        *[chunk("noise") for _ in range(5)],
        chunk("The stiffness rose sharply.", document_id=PAPER_B, page=6),
    ]

    scores = score_retrieval([GOLD, second], contexts, DOCUMENTS)

    assert scores.snippet_ranks == [None, 8]
    assert scores.page_ranks == [2, 8]
    assert scores.recall(5, by_page=True) == 0.5
    assert scores.recall(8, by_page=True) == 1.0
    assert scores.recall(8, by_page=False) == 0.5
    assert scores.reciprocal_rank(by_page=True) == 0.5
    assert scores.reciprocal_rank(by_page=False) == pytest.approx(1 / 8)
    assert RetrievalScores([None], [None]).reciprocal_rank(by_page=True) == 0.0


def result(
    id_: str,
    *,
    answerable: bool = True,
    abstained: bool = False,
    failed: bool = False,
    ragas: RagasScores | None = None,
    retrieval: RetrievalScores | None = None,
    calls: int = 1,
    latency: float = 100.0,
    verified: bool = False,
) -> ItemResult:
    benchmark_item = item(
        id_, type_="single" if answerable else "unanswerable", verified_by="r" if verified else ""
    )
    return ItemResult(
        item=benchmark_item,
        latency_ms=latency,
        usage=RunUsage(calls=calls, input_tokens=100 * calls, output_tokens=10 * calls),
        output=None if failed else ConditionOutput(answer="A.", abstained=abstained),
        error="LLMProviderError: boom" if failed else None,
        retrieval=retrieval,
        ragas=ragas,
        judge_usage=RunUsage(calls=2, input_tokens=50, output_tokens=5),
    )


def test_summary_counts_abstention_both_ways_and_skips_failures() -> None:
    results = [
        result("a1"),
        result("a2", abstained=True),
        result("a3", failed=True),
        result("u1", answerable=False, abstained=True),
        result("u2", answerable=False),
    ]

    summary = summarize(results)

    assert (summary["questions"], summary["failed"]) == (5, 1)
    assert summary["abstention"] == {
        "answerable": 2,
        "false_abstentions": 1,
        "false_abstention_rate": 0.5,
        "unanswerable": 2,
        "correct_abstentions": 1,
        "abstention_accuracy": 0.5,
    }
    assert summary["retrieval"] is None
    assert summary["by_type"] == {"single": 3, "unanswerable": 2}
    assert summary["drafted_by"] == {"claude": 5}


def test_summary_averages_ragas_retrieval_and_system_numbers() -> None:
    results = [
        result(
            "a1",
            ragas=RagasScores(faithfulness=1.0, answer_relevancy=0.8),
            retrieval=RetrievalScores([1], [1]),
            calls=1,
            latency=100,
        ),
        result(
            "a2",
            ragas=RagasScores(faithfulness=None, answer_relevancy=0.6),
            retrieval=RetrievalScores([None], [4]),
            calls=3,
            latency=300,
        ),
        result("u1", answerable=False, abstained=True, latency=200),
    ]

    summary = summarize(results)

    assert summary["ragas"]["faithfulness"] == 1.0
    assert summary["ragas"]["faithfulness_scored"] == 1
    assert summary["ragas"]["answer_relevancy"] == 0.7
    assert summary["retrieval"]["page"] == {"R@5": 1.0, "R@8": 1.0, "MRR": 0.625}
    assert summary["retrieval"]["snippet"] == {"R@5": 0.5, "R@8": 0.5, "MRR": 0.5}
    assert summary["system"]["llm_calls_mean"] == pytest.approx(5 / 3, abs=1e-4)
    assert summary["system"]["latency_ms_p50"] == 200
    assert summary["system"]["latency_ms_p95"] == 300
    assert summary["system"]["judge_calls_total"] == 6
    assert summary["system"]["judge_tokens_total"] == 165


def test_summary_of_nothing_has_no_rates() -> None:
    summary = summarize([])
    assert summary["abstention"]["abstention_accuracy"] is None
    assert summary["system"]["latency_ms_mean"] is None
    assert summary["system"]["latency_ms_p95"] is None
