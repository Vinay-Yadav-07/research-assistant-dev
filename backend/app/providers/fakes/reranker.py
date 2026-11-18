"""Deterministic lexical reranker."""

from collections.abc import Sequence

from app.providers.fakes._text import coverage_score
from app.providers.reranker import RerankerProvider


class FakeReranker(RerankerProvider):
    """Scores by how many distinct query terms and query phrases a passage covers.

    Unlike the fake embedder it ignores term frequency, so it can reorder fused results the way a
    cross-encoder would: a passage covering every query term beats one repeating a single term.
    """

    @property
    def model_name(self) -> str:
        return "fake-coverage-reranker-v1"

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [coverage_score(query, passage) for passage in passages]
