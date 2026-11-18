"""Benchmark metrics (SRS §17.3) for one evaluation run.

Retrieval: a retrieved chunk hits a gold passage when it comes from the gold paper and either
contains the gold snippet (`snippet` hits) or covers the gold page (`page` hits, which include
snippet hits). Per question, Recall@K is the share of its gold passages hit in the top K and
the reciprocal rank uses the first chunk that hits any of them; both are averaged over the
answerable questions with retrieval. Abstention: correct abstentions on unanswerable questions,
false abstentions on answerable ones. Ragas scores average over the answers that have one.
"""

import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.providers.usage import RunUsage
from app.services.retrieval import RetrievedChunk
from eval.conditions import ConditionOutput
from eval.dataset import BenchmarkItem, GoldPassage
from eval.judge import RagasScores

RECALL_KS = (5, 8)


def normalize(text: str) -> str:
    """Lower-case alphanumeric words only, so Markdown and hyphenation differences don't matter."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def hits(
    chunk: RetrievedChunk, passage: GoldPassage, documents: Mapping[str, UUID], *, by_page: bool
) -> bool:
    """True if `chunk` is from the passage's paper and holds its snippet (or covers its page)."""
    if documents.get(passage.paper) != chunk.document_id:
        return False
    if normalize(passage.snippet) in normalize(chunk.text):
        return True
    return by_page and chunk.page_start <= passage.page <= chunk.page_end


@dataclass(frozen=True)
class RetrievalScores:
    """1-based rank of the first chunk hitting each gold passage (None if none did)."""

    snippet_ranks: list[int | None]
    page_ranks: list[int | None]

    def recall(self, k: int, *, by_page: bool) -> float:
        """Share of the gold passages hit in the top `k`."""
        ranks = self.page_ranks if by_page else self.snippet_ranks
        return sum(r is not None and r <= k for r in ranks) / len(ranks)

    def reciprocal_rank(self, *, by_page: bool) -> float:
        """1 / rank of the first hit of any gold passage; 0 without a hit."""
        found = [r for r in (self.page_ranks if by_page else self.snippet_ranks) if r is not None]
        return 1 / min(found) if found else 0.0


def score_retrieval(
    gold: Sequence[GoldPassage], contexts: Sequence[RetrievedChunk], documents: Mapping[str, UUID]
) -> RetrievalScores:
    """Ranks of the gold passages in `contexts`."""

    def first(passage: GoldPassage, by_page: bool) -> int | None:
        return next(
            (
                rank
                for rank, chunk in enumerate(contexts, start=1)
                if hits(chunk, passage, documents, by_page=by_page)
            ),
            None,
        )

    return RetrievalScores(
        snippet_ranks=[first(p, False) for p in gold], page_ranks=[first(p, True) for p in gold]
    )


@dataclass
class ItemResult:
    """Everything recorded for one question in one run."""

    item: BenchmarkItem
    latency_ms: float
    usage: RunUsage
    output: ConditionOutput | None = None
    error: str | None = None
    retrieval: RetrievalScores | None = None
    ragas: RagasScores | None = None
    judge_usage: RunUsage = field(default_factory=RunUsage)
    judge_error: str | None = None


def summarize(results: Sequence[ItemResult]) -> dict[str, Any]:
    """Run metrics; failed questions are counted but excluded from every other metric."""
    done = [r for r in results if r.output is not None]
    answerable = [r for r in done if r.item.answerable]
    unanswerable = [r for r in done if not r.item.answerable]
    with_retrieval = [r.retrieval for r in answerable if r.retrieval is not None]
    answered = [r for r in done if r.output is not None and not r.output.abstained]
    faithfulness = [r.ragas.faithfulness for r in answered if r.ragas is not None]
    relevancy = [r.ragas.answer_relevancy for r in answered if r.ragas is not None]
    latencies = [r.latency_ms for r in done]
    return {
        "questions": len(results),
        "failed": len(results) - len(done),
        "verified": sum(r.item.verified for r in results),
        "drafted_by": _count(r.item.drafted_by for r in results),
        "by_type": _count(r.item.type for r in results),
        "abstention": {
            "answerable": len(answerable),
            "false_abstentions": sum(_abstained(r) for r in answerable),
            "false_abstention_rate": _rate(sum(_abstained(r) for r in answerable), answerable),
            "unanswerable": len(unanswerable),
            "correct_abstentions": sum(_abstained(r) for r in unanswerable),
            "abstention_accuracy": _rate(sum(_abstained(r) for r in unanswerable), unanswerable),
        },
        "retrieval": _retrieval_summary(with_retrieval),
        "ragas": {
            "faithfulness": _mean(faithfulness),
            "faithfulness_scored": sum(v is not None for v in faithfulness),
            "answer_relevancy": _mean(relevancy),
            "answer_relevancy_scored": sum(v is not None for v in relevancy),
            "judge_errors": sum(r.judge_error is not None for r in results),
        },
        "system": {
            "latency_ms_mean": _mean(latencies),
            "latency_ms_p50": statistics.median(latencies) if latencies else None,
            "latency_ms_p95": percentile(latencies, 95),
            "llm_calls_mean": _mean([r.usage.calls for r in done]),
            "input_tokens_mean": _mean([r.usage.input_tokens for r in done]),
            "output_tokens_mean": _mean([r.usage.output_tokens for r in done]),
            "judge_calls_total": sum(r.judge_usage.calls for r in results),
            "judge_tokens_total": sum(r.judge_usage.total_tokens for r in results),
        },
    }


def _retrieval_summary(scores: Sequence[RetrievalScores]) -> dict[str, Any] | None:
    if not scores:
        return None
    summary: dict[str, Any] = {"questions": len(scores)}
    for by_page, label in ((False, "snippet"), (True, "page")):
        summary[label] = {
            **{f"R@{k}": _mean([s.recall(k, by_page=by_page) for s in scores]) for k in RECALL_KS},
            "MRR": _mean([s.reciprocal_rank(by_page=by_page) for s in scores]),
        }
    return summary


def _abstained(result: ItemResult) -> bool:
    return result.output is not None and result.output.abstained


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _rate(count: int, of: Sequence[object]) -> float | None:
    return round(count / len(of), 4) if of else None


def _mean(values: Sequence[float | int | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(statistics.fmean(present), 4) if present else None


def percentile(values: Sequence[float], percent: int) -> float | None:
    """Nearest-rank percentile, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(percent / 100 * len(ordered)) - 1))
    return ordered[index]
