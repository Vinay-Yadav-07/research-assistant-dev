"""NLI provider backed by a local cross-encoder."""

import math
from collections.abc import Callable, Sequence
from typing import Literal

from app.core.errors import ProviderConfigurationError
from app.providers.local._cross_encoder import PairModel, identity_activation, load_cross_encoder
from app.providers.local.runtime import LazyModel, LocalInference
from app.providers.nli import NLIPair, NLIProvider, NLIScores

NLILabel = Literal["entailment", "neutral", "contradiction"]
_LABELS: tuple[NLILabel, ...] = ("entailment", "neutral", "contradiction")


def softmax(logits: Sequence[float]) -> list[float]:
    """Numerically stable softmax."""
    peak = max(logits)
    exps = [math.exp(logit - peak) for logit in logits]
    total = sum(exps)
    return [value / total for value in exps]


def label_order(id2label: dict[int, str]) -> list[NLILabel]:
    """Return the NLI label of each model output index, from the model's `id2label` config.

    Models disagree on output order, so it is never hard-coded.
    """
    names = [id2label[index].strip().lower() for index in sorted(id2label)]
    if sorted(names) != sorted(_LABELS):
        raise ProviderConfigurationError(
            f"NLI model labels {names} are not exactly {list(_LABELS)}.",
            details={"labels": names},
        )
    return [label for name in names for label in _LABELS if label == name]


class CrossEncoderNLI(NLIProvider):
    """Classifies (premise, hypothesis) pairs with an NLI cross-encoder; softmax over 3 labels."""

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
        self._labels: list[NLILabel] | None = None

    @property
    def model_name(self) -> str:
        return self._model_id

    def load(self) -> None:
        """Load the weights now (used when `PRELOAD_MODELS` is on)."""
        self._label_order()

    async def classify(self, pairs: Sequence[NLIPair]) -> list[NLIScores]:
        if not pairs:
            return []
        inputs = [(pair.premise, pair.hypothesis) for pair in pairs]
        return await self._inference.run(lambda: self._classify(inputs))

    def _classify(self, inputs: list[tuple[str, str]]) -> list[NLIScores]:
        labels = self._label_order()
        rows = self._model.get().predict(
            inputs,
            batch_size=self._batch_size,
            activation_fn=self._activation(),
            convert_to_numpy=True,
        )
        results = []
        for row in rows:
            probs = dict(zip(labels, softmax([float(value) for value in row]), strict=True))
            results.append(
                NLIScores(
                    entailment=probs["entailment"],
                    neutral=probs["neutral"],
                    contradiction=probs["contradiction"],
                )
            )
        return results

    def _label_order(self) -> list[NLILabel]:
        if self._labels is None:
            id2label = self._model.get().config.id2label
            self._labels = label_order({int(key): str(value) for key, value in id2label.items()})
        return self._labels
