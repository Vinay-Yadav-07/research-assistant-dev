"""The CPU benchmark and its startup hook, with stub models (no weights, no torch)."""

import asyncio
import logging
import sys
import types
from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.factory import Providers, build_providers
from app.providers.local import benchmark
from app.providers.local.benchmark import NLI_BATCHES, RERANK_POOLS, run_benchmark
from app.providers.nli import NLIPair, NLIScores


class StubLocal:
    """Stands in for every local model; records batch sizes and counts loads."""

    model_name = "stub-local"

    def __init__(self) -> None:
        self.loads = 0
        self.sizes: list[int] = []

    def load(self) -> None:
        self.loads += 1

    async def embed_query(self, text: str) -> list[float]:
        return [1.0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.sizes.append(len(texts))
        return [[1.0] for _ in texts]

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.sizes.append(len(passages))
        return [0.5 for _ in passages]

    async def classify(self, pairs: Sequence[NLIPair]) -> list[NLIScores]:
        self.sizes.append(len(pairs))
        return [NLIScores(entailment=1.0, neutral=0.0, contradiction=0.0) for _ in pairs]


@pytest.fixture
def fake_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    torch = types.ModuleType("torch")
    torch.get_num_threads = lambda: 2  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)


def local_providers(settings: Settings, model: StubLocal) -> Providers:
    providers = build_providers(settings)
    return Providers(**{**providers.__dict__, "embedder": model, "reranker": model, "nli": model})


async def test_refuses_and_logs_an_error_when_providers_are_fakes(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        result = await run_benchmark(build_providers(settings))

    assert result is None
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "embedding (fake-hash-" in record.getMessage()
    assert "reranker (fake-coverage-reranker-v1)" in record.getMessage()
    assert "NLI (" in record.getMessage()


async def test_refuses_when_only_one_provider_is_a_fake(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    providers = build_providers(settings)
    providers = Providers(
        **{**providers.__dict__, "embedder": StubLocal(), "reranker": StubLocal()}
    )

    assert await run_benchmark(providers) is None
    assert "NLI" in caplog.text
    assert "embedding" not in caplog.text.split("configured for")[1]


@pytest.mark.usefixtures("fake_torch")
async def test_table_starts_with_cpu_and_thread_counts(settings: Settings) -> None:
    model = StubLocal()

    table = await run_benchmark(local_providers(settings, model), runs=1)

    assert table is not None
    first_line = table.splitlines()[0]
    assert first_line.startswith("CPUs (os.cpu_count): ")
    assert first_line.endswith("torch threads: 2")
    assert model.loads == 3
    for size in RERANK_POOLS:
        assert f"| reranker | 1 query × {size} passages |" in table
    for size in NLI_BATCHES:
        assert f"| NLI | {size} pairs |" in table
    assert f"| embedding | 20-page paper ({benchmark.PAPER_CHUNKS} chunks) |" in table
    # Each workload runs once to warm up and once timed.
    assert sorted(set(model.sizes)) == sorted({benchmark.PAPER_CHUNKS, *RERANK_POOLS, *NLI_BATCHES})


async def test_startup_benchmark_logs_the_table(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, settings: Settings
) -> None:
    async def table(providers: Providers) -> str:
        return "| Model |"

    monkeypatch.setattr(benchmark, "run_benchmark", table)

    with caplog.at_level(logging.INFO):
        await benchmark.log_startup_benchmark(build_providers(settings))

    assert "CPU benchmark results\n| Model |" in caplog.text


async def test_startup_benchmark_logs_failures_without_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, settings: Settings
) -> None:
    async def broken(providers: Providers) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(benchmark, "run_benchmark", broken)

    await benchmark.log_startup_benchmark(build_providers(settings))

    assert "CPU benchmark failed" in caplog.text
    assert "boom" in caplog.text


@pytest.mark.parametrize("enabled", [True, False])
def test_app_serves_while_the_startup_benchmark_runs_and_cancels_it(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, enabled: bool
) -> None:
    events: list[str] = []

    async def never_finishes(providers: Providers) -> None:
        events.append("started")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    monkeypatch.setattr("app.main.log_startup_benchmark", never_finishes)
    app = create_app(settings.model_copy(update={"run_benchmark_on_startup": enabled}))

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200

    assert events == (["started", "cancelled"] if enabled else [])
