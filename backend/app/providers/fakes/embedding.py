"""Deterministic feature-hashing embedder: lexically similar texts get similar vectors."""

import math
from collections import Counter
from collections.abc import Sequence

from app.providers.embedding import EmbeddingProvider
from app.providers.fakes._text import bigrams, stable_hash, tokenize

_EMPTY_TOKEN = "<empty>"
_BIGRAM_WEIGHT = 0.5


class FakeEmbedder(EmbeddingProvider):
    """Hashes each token and adjacent token pair into a signed bucket, then L2-normalises.

    Identical texts have cosine 1.0, texts sharing words score higher than unrelated ones, and
    results are stable across processes. Queries and documents are embedded the same way.
    """

    def __init__(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return f"fake-hash-{self._dimension}-v1"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def count_tokens(self, text: str) -> int:
        """One token per whitespace-separated word."""
        return len(text.split())

    def _embed(self, text: str) -> list[float]:
        tokens = tokenize(text) or [_EMPTY_TOKEN]
        vector = [0.0] * self._dimension
        features = [(Counter(tokens), 1.0), (Counter(bigrams(tokens)), _BIGRAM_WEIGHT)]
        for counts, weight in features:
            for feature, count in counts.items():
                digest = stable_hash(feature)
                sign = 1.0 if (digest >> 32) & 1 else -1.0
                vector[digest % self._dimension] += sign * weight * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Opposite-signed features cancelled in shared buckets; never return a zero vector.
            return [1.0] + [0.0] * (self._dimension - 1)
        return [value / norm for value in vector]
