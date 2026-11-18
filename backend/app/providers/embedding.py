"""Embedding provider interface."""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Turns text into L2-normalised vectors of a fixed dimension.

    Output order matches input order and every vector has length `dimension`. Documents and
    queries are separate calls because some models (e.g. bge) prefix queries with an instruction.
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages for indexing."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens the model sees for `text`, without special tokens (D-044, D-055).

        Blocking: may load the model on first use, so call it from a worker thread.
        """
        ...
