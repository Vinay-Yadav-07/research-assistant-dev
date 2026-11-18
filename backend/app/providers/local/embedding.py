"""Embedding provider backed by a local sentence-transformers model."""

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from app.core.errors import ProviderConfigurationError
from app.providers.embedding import EmbeddingProvider
from app.providers.local.runtime import LazyModel, LocalInference


class EncoderModel(Protocol):
    """The part of `sentence_transformers.SentenceTransformer` this provider uses."""

    def encode(
        self,
        inputs: list[str],
        *,
        prompt: str | None,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> Any: ...

    def get_embedding_dimension(self) -> int | None: ...

    # A Hugging Face tokenizer.
    tokenizer: Any


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Embeds with a sentence-transformers model; queries get the model's instruction prefix.

    The configured dimension is checked against the model when it loads, so a mismatch with the
    `chunks.embedding` column fails loudly instead of at insert time.
    """

    def __init__(
        self,
        *,
        model_id: str,
        dimension: int,
        query_prefix: str,
        batch_size: int,
        inference: LocalInference,
        loader: Callable[[], EncoderModel] | None = None,
    ) -> None:
        self._model_id = model_id
        self._dimension = dimension
        self._query_prefix = query_prefix
        self._batch_size = batch_size
        self._inference = inference
        self._model = LazyModel(self._checked(loader or self._load_sentence_transformer))

    @property
    def model_name(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def load(self) -> None:
        """Load the weights now (used when `PRELOAD_MODELS` is on)."""
        self._model.get()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._inference.run(lambda: self._encode(list(texts), prompt=None))

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._inference.run(lambda: self._encode([text], self._query_prefix))
        return vectors[0]

    def count_tokens(self, text: str) -> int:
        # verbose=False: long texts are only counted, so the max-length warning is noise.
        encoded = self._model.get().tokenizer(text, add_special_tokens=False, verbose=False)
        return len(encoded["input_ids"])

    def _encode(self, texts: list[str], prompt: str | None) -> list[list[float]]:
        vectors = self._model.get().encode(
            texts,
            prompt=prompt or None,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector] for vector in vectors]

    def _checked(self, loader: Callable[[], EncoderModel]) -> Callable[[], EncoderModel]:
        def load_and_check() -> EncoderModel:
            model = loader()
            actual = model.get_embedding_dimension()
            if actual != self._dimension:
                raise ProviderConfigurationError(
                    f"Embedding model '{self._model_id}' produces {actual}-dim vectors but "
                    f"EMBEDDING_DIMENSION is {self._dimension}.",
                    details={"model": self._model_id, "model_dimension": actual},
                )
            return model

        return load_and_check

    def _load_sentence_transformer(self) -> EncoderModel:
        from sentence_transformers import SentenceTransformer

        model: EncoderModel = SentenceTransformer(self._model_id, device="cpu")
        return model
