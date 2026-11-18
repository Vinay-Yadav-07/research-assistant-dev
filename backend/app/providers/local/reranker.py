"""Reranker provider backed by a local cross-encoder."""

import math
from collections.abc import Callable, Sequence

from app.providers.local._cross_encoder import PairModel, identity_activation, load_cross_encoder
from app.providers.local.runtime import LazyModel, LocalInference
from app.providers.reranker import RerankerProvider


def sigmoid(logit: float) -> float:
    """Map a cross-encoder logit to [0, 1] without overflow."""
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp = math.exp(logit)
    return exp / (1.0 + exp)


class CrossEncoderReranker(RerankerProvider):
    """Scores query–passage pairs with a cross-encoder; scores are sigmoid(logit) (SRS §8.2)."""

    def __init__(
        self,
        *,
        model_id: str,
        max_length: int,
        batch_size: int,
        inference: LocalInference,
        loader: Callable[[], PairModel] | None = None,
        activation: Callable[[], object] = identity_activation,
    ) -> None:
        self._model_id = model_id
        self._batch_size = batch_size
        self._inference = inference
        self._activation = activation
        self._model = LazyModel(loader or (lambda: load_cross_encoder(model_id, max_length)))

    @property
    def model_name(self) -> str:
        return self._model_id

    def load(self) -> None:
        """Load the weights now (used when `PRELOAD_MODELS` is on)."""
        self._model.get()

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        pairs = [(query, passage) for passage in passages]
        return await self._inference.run(lambda: self._score(pairs))

    def _score(self, pairs: list[tuple[str, str]]) -> list[float]:
        logits = self._model.get().predict(
            pairs,
            batch_size=self._batch_size,
            activation_fn=self._activation(),
            convert_to_numpy=True,
        )
        return [sigmoid(float(logit)) for logit in logits]
