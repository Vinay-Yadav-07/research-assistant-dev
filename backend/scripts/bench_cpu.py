"""CPU inference benchmark for the local models (Phase 1 exit criterion, D-024).

Run from `backend/` (locally or inside the container): `python -m scripts.bench_cpu`.
Prints a Markdown table to paste into docs/PROGRESS.md and writes the experiment JSON
(`scripts/experiment_log.py`). Workloads and timing come from `app.providers.local.benchmark`.
On the Space, set `RUN_BENCHMARK_ON_STARTUP=true` instead (docs/SETUP.md).
"""

import argparse
import asyncio
import time
from typing import Any

from app.core.config import Settings, get_settings
from app.providers.factory import build_providers, preload_models
from app.providers.local.benchmark import (
    NLI_BATCHES,
    PAPER_CHUNKS,
    PASSAGE_WORDS,
    RERANK_POOLS,
    fake_providers,
    measure,
    workloads,
)
from scripts.experiment_log import write_experiment


async def run(settings: Settings, runs: int) -> None:
    """Load the models, time every workload, print the table, and write the JSON."""
    providers = build_providers(settings)
    fakes = fake_providers(providers)
    if fakes:
        raise SystemExit(f"fake provider configured for {', '.join(fakes)}")
    started = time.perf_counter()
    await asyncio.to_thread(preload_models, providers)
    load_seconds = time.perf_counter() - started

    results: list[dict[str, Any]] = []
    print("| Model | Workload | p50 (ms) | p95 (ms) |\n|---|---|---|---|")
    for model, workload, func in workloads(providers):
        p50, p95 = await measure(func, runs)
        results.append({"model": model, "workload": workload, "p50_ms": p50, "p95_ms": p95})
        print(f"| {model} | {workload} | {p50:.0f} | {p95:.0f} |", flush=True)

    path = write_experiment(
        "bench_cpu",
        settings=settings,
        models={
            "embedding": providers.embedder.model_name,
            "reranker": providers.reranker.model_name,
            "nli": providers.nli.model_name,
        },
        dataset="synthetic",
        parameters={
            "runs": runs,
            "passage_words": PASSAGE_WORDS,
            "paper_chunks": PAPER_CHUNKS,
            "rerank_pools": list(RERANK_POOLS),
            "nli_batches": list(NLI_BATCHES),
        },
        results=results,
        summary={"load_seconds": round(load_seconds, 1)},
    )
    print(f"\nModels loaded in {load_seconds:.1f} s. Wrote {path}")


def main() -> None:
    """Build the local-model providers and run the benchmark."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="timed runs per workload")
    args = parser.parse_args()
    settings = get_settings().model_copy(
        update={
            "embedding_provider": "sentence_transformers",
            "reranker_provider": "cross_encoder",
            "nli_provider": "cross_encoder",
        }
    )
    asyncio.run(run(settings, args.runs))


if __name__ == "__main__":
    main()
