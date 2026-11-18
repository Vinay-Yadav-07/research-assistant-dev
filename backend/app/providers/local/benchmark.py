"""CPU inference benchmark for the local models (D-024).

Used by `scripts/bench_cpu.py` and, when `RUN_BENCHMARK_ON_STARTUP` is on, run once in the
background at startup so the deployed tier's numbers appear in the logs. Workloads are sized like
Phase 1–2 calls with synthetic ~400-token passages, so no corpus or database is needed.
"""

import asyncio
import logging
import os
import statistics
import time
from collections.abc import Awaitable, Callable
from functools import partial

from app.providers.factory import Providers, preload_models
from app.providers.fakes import FakeEmbedder, FakeNLI, FakeReranker
from app.providers.nli import NLIPair

logger = logging.getLogger(__name__)

# ~60 words; repeated to reach roughly chunk size without needing a corpus.
_PARAGRAPH = (
    "Electrospun polycaprolactone scaffolds were seeded with human mesenchymal stem cells and "
    "cultured for 21 days in osteogenic medium. Alkaline phosphatase activity and calcium "
    "deposition increased with fibre alignment, while cell viability remained above ninety "
    "percent. Scaffolds with a mean fibre diameter of 800 nm showed the highest expression of "
    "RUNX2 and osteocalcin compared with randomly oriented controls. "
)
_QUERY = "How does fibre alignment affect osteogenic differentiation of stem cells on scaffolds?"
_CLAIM = "Aligned fibres increased calcium deposition compared with random fibres."
PASSAGE_WORDS = 300  # ~400 tokens
PAPER_CHUNKS = 40  # a 20-page paper at ~400-token chunks with ~12% overlap (D-044)
RERANK_POOLS = (20, 30)
NLI_BATCHES = (8, 24)

Workload = tuple[str, str, Callable[[], Awaitable[object]]]


def passage(index: int, words: int = PASSAGE_WORDS) -> str:
    """A distinct passage of about `words` words."""
    text = f"Passage {index}. " + _PARAGRAPH * (words // 60 + 1)
    return " ".join(text.split()[:words])


def fake_providers(providers: Providers) -> list[str]:
    """Names of the local-model slots that hold a fake, which would make the numbers meaningless."""
    slots = (
        ("embedding", providers.embedder, FakeEmbedder),
        ("reranker", providers.reranker, FakeReranker),
        ("NLI", providers.nli, FakeNLI),
    )
    return [
        f"{name} ({provider.model_name})"
        for name, provider, fake in slots
        if isinstance(provider, fake)
    ]


async def measure(func: Callable[[], Awaitable[object]], runs: int) -> tuple[float, float]:
    """Run once to warm up, then `runs` times; return (p50, p95) in milliseconds."""
    await func()
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        await func()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[min(len(samples) - 1, round(0.95 * (len(samples) - 1)))]
    return statistics.median(samples), p95


def workloads(providers: Providers) -> list[Workload]:
    """The benchmark workloads, in the order they are reported."""
    paper = [passage(i) for i in range(PAPER_CHUNKS)]
    result: list[Workload] = [
        ("embedding", "1 query", partial(providers.embedder.embed_query, _QUERY)),
        (
            "embedding",
            f"20-page paper ({PAPER_CHUNKS} chunks)",
            partial(providers.embedder.embed_documents, paper),
        ),
    ]
    for size in RERANK_POOLS:
        pool = [passage(i) for i in range(size)]
        result.append(
            (
                "reranker",
                f"1 query × {size} passages",
                partial(providers.reranker.score, _QUERY, pool),
            )
        )
    for size in NLI_BATCHES:
        pairs = [NLIPair(premise=passage(i), hypothesis=_CLAIM) for i in range(size)]
        result.append(("NLI", f"{size} pairs", partial(providers.nli.classify, pairs)))
    return result


async def run_benchmark(providers: Providers, runs: int = 3) -> str | None:
    """Load the local models, time every workload, and return a Markdown table.

    Refuses (logs an ERROR, returns None) if any local-model slot holds a fake provider.
    """
    fakes = fake_providers(providers)
    if fakes:
        logger.error("CPU benchmark not run: fake provider configured for %s", ", ".join(fakes))
        return None

    started = time.perf_counter()
    await asyncio.to_thread(preload_models, providers)
    load_seconds = time.perf_counter() - started
    # Importing torch takes ~1 s; keep it off the event loop.
    torch_threads = await asyncio.to_thread(_torch_threads)

    lines = [
        f"CPUs (os.cpu_count): {os.cpu_count()} · torch threads: {torch_threads}",
        f"Models: {providers.embedder.model_name}, {providers.reranker.model_name}, "
        f"{providers.nli.model_name} · load {load_seconds:.1f} s · ~{PASSAGE_WORDS}-word "
        f"passages · {runs} timed runs",
        "",
        "| Model | Workload | p50 (ms) | p95 (ms) |",
        "|---|---|---|---|",
    ]
    for model, workload, func in workloads(providers):
        p50, p95 = await measure(func, runs)
        lines.append(f"| {model} | {workload} | {p50:.0f} | {p95:.0f} |")
    return "\n".join(lines)


def _torch_threads() -> int:
    import torch

    return torch.get_num_threads()


async def log_startup_benchmark(providers: Providers) -> None:
    """Run the benchmark once and log the table; never raises (except on cancellation)."""
    logger.info("CPU benchmark started (RUN_BENCHMARK_ON_STARTUP)")
    try:
        table = await run_benchmark(providers)
    except Exception:
        logger.exception("CPU benchmark failed")
        return
    if table is not None:
        logger.info("CPU benchmark results\n%s", table)
