"""Shared machinery for local models: lazy loading, worker threads, and a concurrency limit."""

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Generic, Protocol, TypeVar, runtime_checkable

from huggingface_hub import try_to_load_from_cache

ModelT = TypeVar("ModelT")
ResultT = TypeVar("ResultT")


@runtime_checkable
class LocalModel(Protocol):
    """A provider backed by local weights that can be loaded ahead of first use."""

    def load(self) -> None:
        """Load the weights now (blocking). Safe to call more than once."""
        ...


class LocalInference:
    """Runs blocking inference in worker threads, at most `concurrency` calls at a time.

    One instance is shared by every local model, so CPU-bound work never blocks the event loop
    and concurrent requests queue instead of oversubscribing the CPU.
    """

    def __init__(self, concurrency: int) -> None:
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self, func: Callable[[], ResultT]) -> ResultT:
        """Run `func` in a worker thread once a slot is free."""
        async with self._semaphore:
            return await asyncio.to_thread(func)


class LazyModel(Generic[ModelT]):
    """Loads a model once, on first use or on an explicit `load()`, from any thread."""

    def __init__(self, loader: Callable[[], ModelT]) -> None:
        self._loader = loader
        self._model: ModelT | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def get(self) -> ModelT:
        """Return the model, loading it first if needed (blocking)."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._loader()
        return self._model


def cached_hidden_size(model_id: str) -> int | None:
    """Read `hidden_size` from the model's `config.json` without loading weights.

    Looks in a local model directory or the Hugging Face cache only; returns None when the
    config is not available offline, so the caller checks again once the model loads.
    """
    local = Path(model_id) / "config.json"
    path: object = local if local.is_file() else try_to_load_from_cache(model_id, "config.json")
    if not isinstance(path, str | Path):
        return None
    hidden_size = json.loads(Path(path).read_text(encoding="utf-8")).get("hidden_size")
    return hidden_size if isinstance(hidden_size, int) else None
