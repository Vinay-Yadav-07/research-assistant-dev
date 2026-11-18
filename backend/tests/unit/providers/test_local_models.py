"""Local model providers, tested with stub models: no weights, no torch, no network."""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ProviderConfigurationError
from app.main import create_app
from app.providers import factory
from app.providers.factory import build_providers, preload_models
from app.providers.fakes import FakeEmbedder
from app.providers.local import (
    CrossEncoderNLI,
    CrossEncoderReranker,
    LocalInference,
    SentenceTransformerEmbedder,
    cached_hidden_size,
    runtime,
)
from app.providers.local.nli import label_order, softmax
from app.providers.local.reranker import sigmoid
from app.providers.nli import NLIPair

IDENTITY = "identity"


class StubEncoder:
    """Returns one fixed unit vector per input and records each call."""

    def __init__(self, dimension: int = 4) -> None:
        self.dimension = dimension
        self.calls: list[dict[str, Any]] = []

    def encode(self, inputs: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append({"inputs": inputs, **kwargs})
        return [[float(len(text)), 0.0, 0.0, 0.0][: self.dimension] for text in inputs]

    def get_embedding_dimension(self) -> int:
        return self.dimension

    def tokenizer(self, text: str, **kwargs: Any) -> dict[str, list[int]]:
        """Character-level stand-in for a Hugging Face tokenizer; records its options."""
        self.calls.append({"tokenize": text, **kwargs})
        return {"input_ids": [ord(char) for char in text]}


class StubPairModel:
    """Returns scripted logits per pair and exposes an `id2label` config."""

    def __init__(self, logits: list[Any], id2label: dict[int, str] | None = None) -> None:
        self.logits = logits
        self.config = type("Config", (), {"id2label": id2label or {}})()
        self.calls: list[dict[str, Any]] = []

    def predict(self, inputs: list[tuple[str, str]], **kwargs: Any) -> list[Any]:
        self.calls.append({"inputs": inputs, **kwargs})
        return self.logits[: len(inputs)]


class CountingLoader:
    def __init__(self, model: Any) -> None:
        self.model = model
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.model


def make_embedder(loader: Any, dimension: int = 4) -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(
        model_id="stub-embedder",
        dimension=dimension,
        query_prefix="query: ",
        batch_size=8,
        inference=LocalInference(1),
        loader=loader,
    )


def make_reranker(model: StubPairModel) -> CrossEncoderReranker:
    return CrossEncoderReranker(
        model_id="stub-reranker",
        max_length=512,
        batch_size=8,
        inference=LocalInference(1),
        loader=lambda: model,
        activation=lambda: IDENTITY,
    )


def make_nli(model: StubPairModel) -> CrossEncoderNLI:
    return CrossEncoderNLI(
        model_id="stub-nli",
        max_length=512,
        batch_size=8,
        inference=LocalInference(1),
        loader=lambda: model,
        activation=lambda: IDENTITY,
    )


# --- embedding ---


async def test_embedder_returns_float_lists_in_input_order() -> None:
    embedder = make_embedder(lambda: StubEncoder())

    vectors = await embedder.embed_documents(["a", "abc"])

    assert vectors == [[1.0, 0.0, 0.0, 0.0], [3.0, 0.0, 0.0, 0.0]]
    assert all(isinstance(value, float) for value in vectors[0])


async def test_embedder_normalizes_and_prefixes_queries_only() -> None:
    model = StubEncoder()
    embedder = make_embedder(lambda: model)

    await embedder.embed_documents(["passage"])
    await embedder.embed_query("question")

    assert model.calls[0]["prompt"] is None
    assert model.calls[1]["prompt"] == "query: "
    assert all(call["normalize_embeddings"] for call in model.calls)
    assert model.calls[0]["batch_size"] == 8


async def test_embedder_reports_model_name_and_dimension() -> None:
    embedder = make_embedder(lambda: StubEncoder())

    assert embedder.model_name == "stub-embedder"
    assert embedder.dimension == 4


async def test_embedder_loads_lazily_and_once() -> None:
    loader = CountingLoader(StubEncoder())
    embedder = make_embedder(loader)

    assert loader.calls == 0
    assert await embedder.embed_documents([]) == []
    assert loader.calls == 0

    await embedder.embed_query("q")
    await embedder.embed_documents(["p"])
    embedder.load()

    assert loader.calls == 1


def test_embedder_counts_tokens_without_special_tokens() -> None:
    stub = StubEncoder()
    embedder = make_embedder(lambda: stub)

    assert embedder.count_tokens("abc") == 3
    assert stub.calls[-1] == {"tokenize": "abc", "add_special_tokens": False, "verbose": False}


async def test_embedder_dimension_mismatch_fails_on_load() -> None:
    embedder = make_embedder(lambda: StubEncoder(dimension=4), dimension=768)

    with pytest.raises(ProviderConfigurationError, match="4-dim.*EMBEDDING_DIMENSION is 768"):
        await embedder.embed_query("q")


# --- reranker ---


@pytest.mark.parametrize(("logit", "expected"), [(0.0, 0.5), (1000.0, 1.0), (-1000.0, 0.0)])
def test_sigmoid_is_stable(logit: float, expected: float) -> None:
    assert sigmoid(logit) == pytest.approx(expected)


async def test_reranker_maps_raw_logits_to_unit_interval_in_order() -> None:
    model = StubPairModel([2.0, -2.0, 0.0])
    reranker = make_reranker(model)

    scores = await reranker.score("q", ["a", "b", "c"])

    assert scores == pytest.approx([sigmoid(2.0), sigmoid(-2.0), 0.5])
    assert model.calls[0]["inputs"] == [("q", "a"), ("q", "b"), ("q", "c")]
    assert model.calls[0]["activation_fn"] == IDENTITY


async def test_reranker_with_no_passages_does_not_load() -> None:
    loader = CountingLoader(StubPairModel([]))
    reranker = CrossEncoderReranker(
        model_id="stub",
        max_length=512,
        batch_size=8,
        inference=LocalInference(1),
        loader=loader,
    )

    assert await reranker.score("q", []) == []
    assert loader.calls == 0


# --- NLI ---


def test_softmax_sums_to_one() -> None:
    probabilities = softmax([1000.0, 0.0, -1000.0])

    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities[0] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "id2label",
    [
        {0: "contradiction", 1: "entailment", 2: "neutral"},
        {0: "ENTAILMENT", 1: "NEUTRAL", 2: "CONTRADICTION"},
    ],
)
async def test_nli_uses_the_models_label_order(id2label: dict[int, str]) -> None:
    entail_index = next(i for i, name in id2label.items() if name.lower() == "entailment")
    row = [0.0, 0.0, 0.0]
    row[entail_index] = 10.0
    nli = make_nli(StubPairModel([row], id2label))

    [scores] = await nli.classify([NLIPair(premise="p", hypothesis="h")])

    assert scores.entailment > 0.99
    assert scores.entailment + scores.neutral + scores.contradiction == pytest.approx(1.0)


def test_nli_rejects_unexpected_labels() -> None:
    with pytest.raises(ProviderConfigurationError, match="labels"):
        label_order({0: "LABEL_0", 1: "LABEL_1"})


async def test_nli_load_checks_labels_and_empty_input_skips_model() -> None:
    nli = make_nli(StubPairModel([], {0: "yes", 1: "no", 2: "maybe"}))

    assert await nli.classify([]) == []
    with pytest.raises(ProviderConfigurationError):
        nli.load()


# --- concurrency ---


@pytest.mark.parametrize("limit", [1, 2])
async def test_local_inference_limits_concurrent_calls(limit: int) -> None:
    inference = LocalInference(limit)
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def work() -> None:
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.02)
        with lock:
            state["running"] -= 1

    await asyncio.gather(*(inference.run(work) for _ in range(5)))

    assert state["peak"] == limit


async def test_local_inference_runs_off_the_event_loop_thread() -> None:
    thread_ids = await LocalInference(1).run(lambda: threading.get_ident())

    assert thread_ids != threading.get_ident()


def test_local_inference_needs_a_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        LocalInference(0)


# --- cached config ---


def test_cached_hidden_size_reads_a_local_model_dir(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"hidden_size": 768}))

    assert cached_hidden_size(str(tmp_path)) == 768


def test_cached_hidden_size_is_none_when_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "try_to_load_from_cache", lambda *args, **kwargs: None)

    assert cached_hidden_size("some/uncached-model") is None


def test_cached_hidden_size_reads_the_hub_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"hidden_size": 384}))
    monkeypatch.setattr(runtime, "try_to_load_from_cache", lambda *args, **kwargs: str(config))

    assert cached_hidden_size("BAAI/some-model") == 384


# --- factory and startup ---


def local(settings: Settings, **overrides: object) -> Settings:
    update: dict[str, object] = {
        "embedding_provider": "sentence_transformers",
        "reranker_provider": "cross_encoder",
        "nli_provider": "cross_encoder",
        **overrides,
    }
    return settings.model_copy(update=update)


def test_factory_builds_local_providers_without_loading_weights(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(factory, "cached_hidden_size", lambda model_id: None)
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

    providers = build_providers(local(settings))

    assert isinstance(providers.embedder, SentenceTransformerEmbedder)
    assert isinstance(providers.reranker, CrossEncoderReranker)
    assert isinstance(providers.nli, CrossEncoderNLI)
    assert providers.embedder.model_name == "BAAI/bge-small-en-v1.5"
    assert "sentence_transformers" not in sys.modules


def test_factory_rejects_a_cached_dimension_mismatch(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(factory, "cached_hidden_size", lambda model_id: 768)

    with pytest.raises(ProviderConfigurationError, match="dimension 768.*384"):
        build_providers(local(settings))


def test_factory_accepts_a_cached_matching_dimension(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(factory, "cached_hidden_size", lambda model_id: 384)

    assert isinstance(build_providers(local(settings)).embedder, SentenceTransformerEmbedder)


def test_preload_loads_only_local_models(settings: Settings) -> None:
    loader = CountingLoader(StubEncoder())
    providers = build_providers(settings)
    providers = factory.Providers(
        **{**providers.__dict__, "embedder": make_embedder(loader)},
    )

    preload_models(providers)

    assert loader.calls == 1
    assert isinstance(build_providers(settings).embedder, FakeEmbedder)


@pytest.mark.parametrize("preload", [True, False])
def test_startup_preloads_only_when_configured(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, preload: bool
) -> None:
    calls: list[object] = []
    monkeypatch.setattr("app.main.preload_models", calls.append)

    with TestClient(create_app(settings.model_copy(update={"preload_models": preload}))):
        pass

    assert len(calls) == (1 if preload else 0)
