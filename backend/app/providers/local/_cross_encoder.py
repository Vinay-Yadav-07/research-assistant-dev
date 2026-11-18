"""Loading for cross-encoder models shared by the reranker and NLI providers."""

from typing import Any, Protocol


class PairModel(Protocol):
    """The part of `sentence_transformers.CrossEncoder` the providers use."""

    @property
    def config(self) -> Any: ...

    def predict(
        self,
        inputs: list[tuple[str, str]],
        *,
        batch_size: int,
        activation_fn: Any,
        convert_to_numpy: bool,
    ) -> Any: ...


def load_cross_encoder(model_id: str, max_length: int) -> PairModel:
    """Load a CrossEncoder on CPU; inputs longer than `max_length` tokens are truncated."""
    from sentence_transformers import CrossEncoder

    model: PairModel = CrossEncoder(model_id, device="cpu", max_length=max_length)
    return model


def identity_activation() -> Any:
    """An activation that returns raw logits, so normalization stays in our code."""
    import torch

    return torch.nn.Identity()
