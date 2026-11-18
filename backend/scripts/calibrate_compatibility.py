"""Calibrate the compatibility threshold (FR-22, D-060) on the benchmark papers.

Run from `backend/`:
    uv run python -m scripts.calibrate_compatibility --papers-dir scripts/data/papers \\
        --off-topic path/to/unrelated.pdf [more.pdf ...]

Each on-topic paper is scored against a workspace of the other papers (leave-one-out); each
off-topic paper against a workspace of all of them. Workspace documents get the stored vector
(first chunks of the whole parse); candidates the pre-upload vector (first pages only), as in
the app. The suggested threshold is the midpoint between the lowest on-topic and the highest
off-topic score. Uses the configured local models (bge-small) and PyMuPDF4LLM.
"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.providers.factory import build_providers
from app.repositories.topic_profiles import ProfileState
from app.services.compatibility import pdf_vector
from app.services.ingestion import IngestionOptions
from app.services.topic_profile import CompatibilityOptions, add_to_centroid, similarity
from scripts.experiment_log import write_experiment


def centroid(vectors: list[list[float]]) -> ProfileState:
    """A profile built incrementally, as the app builds it."""
    state = ProfileState(centroid=None, document_count=0)
    for vector in vectors:
        state = add_to_centroid(state, vector)
    return state


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers-dir", type=Path, default=Path("scripts/data/papers"))
    parser.add_argument("--off-topic", type=Path, nargs="*", default=[])
    args = parser.parse_args()

    settings = get_settings().model_copy(
        update={"parser_provider": "pymupdf4llm", "embedding_provider": "sentence_transformers"}
    )
    providers = build_providers(settings)
    options = CompatibilityOptions.from_settings(settings)
    ingestion = IngestionOptions.from_settings(settings)

    async def vector(path: Path, max_pages: int | None) -> list[float]:
        return await pdf_vector(
            await asyncio.to_thread(path.read_bytes),
            parser=providers.parser,
            embedder=providers.embedder,
            ingestion=ingestion,
            first_chunks=options.first_chunks,
            max_pages=max_pages,
        )

    papers = sorted(args.papers_dir.glob("*.pdf"))
    stored = {path: await vector(path, None) for path in papers}
    print(f"first_chunks={options.first_chunks} max_pages={options.max_pages}\n")
    print(f"{'paper':60} {'fast':>6} {'stored':>6}")
    results: list[dict[str, Any]] = []
    on_topic: list[float] = []
    for path in papers:
        others = centroid([stored[other] for other in papers if other != path])
        fast = similarity(others, await vector(path, options.max_pages)) or 0.0
        full = similarity(others, stored[path]) or 0.0
        on_topic.append(fast)
        results.append({"paper": path.name, "on_topic": True, "fast": fast, "stored": full})
        print(f"{path.stem:60} {fast:6.3f} {full:6.3f}")

    everything = centroid(list(stored.values()))
    off_topic: list[float] = []
    for path in args.off_topic:
        fast = similarity(everything, await vector(path, options.max_pages)) or 0.0
        off_topic.append(fast)
        results.append({"paper": path.name, "on_topic": False, "fast": fast, "stored": None})
        print(f"{'[off-topic] ' + path.stem:60} {fast:6.3f}")

    summary: dict[str, float | None] = {
        "lowest_on_topic": min(on_topic),
        "highest_off_topic": None,
        "suggested_threshold": None,
    }
    print(f"\nlowest on-topic: {min(on_topic):.3f}")
    if off_topic:
        highest = max(off_topic)
        threshold = round((min(on_topic) + highest) / 2, 2)
        summary.update(highest_off_topic=highest, suggested_threshold=threshold)
        print(f"highest off-topic: {highest:.3f}")
        print(f"suggested threshold: {threshold:.2f}")

    path = write_experiment(
        "calibrate_compatibility",
        settings=settings,
        models={"embedding": providers.embedder.model_name, "parser": settings.parser_provider},
        dataset=str(args.papers_dir),
        parameters={"first_chunks": options.first_chunks, "max_pages": options.max_pages},
        results=results,
        summary=summary,
    )
    print(f"\nWrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
