"""Parse and chunk real papers and print a per-paper report (task #4 check).

Run from `backend/`:
    uv run python -m scripts.parse_papers --papers-dir scripts/data/papers
    uv run python -m scripts.parse_papers --show-chunks Plasmonic_Nanomaterials.pdf

Uses the configured embedding model's tokenizer and the chunking settings from config, so the
numbers match what ingestion will produce.
"""

import argparse
import asyncio
import statistics
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.providers.local import LocalInference, SentenceTransformerEmbedder
from app.providers.local.pdf_parser import (
    PyMuPDF4LLMParser,
    average_text_chars_per_page,
    page_texts,
)
from app.services.chunking import ChunkDraft, chunk_pages
from app.services.page_cleanup import remove_repeated_lines


async def process(
    data: bytes, parser: PyMuPDF4LLMParser, embedder: SentenceTransformerEmbedder
) -> tuple[float, int, list[ChunkDraft], dict[str, int]]:
    """Average text chars per page, page count, chunks, and removed boilerplate for one PDF."""
    settings = get_settings()
    with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
        average = average_text_chars_per_page(page_texts(document))
    parsed = await parser.parse(data)
    cleaned = remove_repeated_lines(
        parsed.pages,
        min_pages=settings.boilerplate_min_pages,
        min_page_fraction=settings.boilerplate_min_page_fraction,
        max_line_chars=settings.boilerplate_max_line_chars,
    )
    chunks = await asyncio.to_thread(
        chunk_pages,
        cleaned.pages,
        count_tokens=embedder.count_tokens,
        min_tokens=settings.chunk_min_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
        merge_below_tokens=settings.chunk_merge_below_tokens,
        hard_max_tokens=settings.chunk_hard_max_tokens,
    )
    return average, parsed.page_count, chunks, cleaned.removed


async def run(args: argparse.Namespace, papers: dict[str, bytes]) -> None:
    settings = get_settings()
    parser = PyMuPDF4LLMParser(min_text_chars_per_page=settings.pdf_min_text_chars_per_page)
    embedder = SentenceTransformerEmbedder(
        model_id=settings.embedding_model,
        dimension=settings.embedding_dimension,
        query_prefix=settings.embedding_query_prefix,
        batch_size=settings.embedding_batch_size,
        inference=LocalInference(1),
    )
    print(
        "| Paper | Pages | Avg chars/page | Chunks | Tokens min / median / max "
        f"| Under {settings.chunk_merge_below_tokens} | Sections |"
    )
    print("|---|---:|---:|---:|---|---:|---:|")
    removed_by_paper: dict[str, dict[str, int]] = {}
    shown: list[ChunkDraft] = []
    for name, data in papers.items():
        average, pages, chunks, removed = await process(data, parser, embedder)
        tokens = [chunk.token_count for chunk in chunks]
        sections = len({chunk.section for chunk in chunks})
        print(
            f"| {name} | {pages} | {average:.0f} | {len(chunks)} | "
            f"{min(tokens)} / {statistics.median(tokens):.0f} / {max(tokens)} | "
            f"{sum(t < settings.chunk_merge_below_tokens for t in tokens)} | {sections} |"
        )
        removed_by_paper[name] = removed
        if name == args.show_chunks:
            shown = chunks[args.start : args.start + args.count]
    print("\nRemoved boilerplate (normalized line: pages):")
    for name, removed in removed_by_paper.items():
        lines = ", ".join(f"{key!r}: {count}" for key, count in removed.items()) or "none"
        print(f"- {name}: {lines}")
    if args.show_chunks:
        print(f"\nChunks {args.start}-{args.start + args.count - 1} of {args.show_chunks}:")
        for chunk in shown:
            print(
                f"\n--- chunk {chunk.chunk_index} | pages {chunk.page_start}-{chunk.page_end} | "
                f"section {chunk.section!r} | {chunk.token_count} tokens ---\n{chunk.text}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--papers-dir", default="scripts/data/papers")
    parser.add_argument("--show-chunks", default=None, help="file name whose chunks to print")
    parser.add_argument("--start", type=int, default=0, help="first chunk index to print")
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    papers = {path.name: path.read_bytes() for path in sorted(Path(args.papers_dir).glob("*.pdf"))}
    asyncio.run(run(args, papers))


if __name__ == "__main__":
    main()
