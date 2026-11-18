"""Reranker provider interface."""

from collections.abc import Sequence
from typing import Protocol


class RerankerProvider(Protocol):
    """Scores query–passage relevance. Sorting and top-k selection belong to the caller."""

    @property
    def model_name(self) -> str: ...

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Return one relevance score in [0, 1] per passage, in input order (higher = better)."""
        ...
