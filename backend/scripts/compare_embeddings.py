"""Sanity check: compare embedding models on dense retrieval over a few real papers (D-048).

Run from `backend/`:
    uv run python -m scripts.compare_embeddings --questions path/to/questions.json

The questions file names the PDFs (relative to the file) and gives each question a gold answer
snippet and page:

    {"papers": [{"id": "p1", "file": "paper1.pdf"}],
     "questions": [{"paper": "p1", "question": "...", "snippet": "...", "page": 3}]}

Every model sees the same chunks: ~400 tokens (D-044, counted with the model's tokenizer; bge
small and base share one) with ~12% overlap, cut on word boundaries and tagged with their pages.
Retrieval is dense-only over all papers' chunks together, like a workspace. A retrieved chunk is
a hit if it contains the snippet (strict) or covers the gold page (lenient). With ~15 questions
only large differences mean anything.
"""

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf4llm  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.providers.local import LocalInference, SentenceTransformerEmbedder
from scripts.experiment_log import write_experiment

DEFAULT_MODELS = (("BAAI/bge-small-en-v1.5", 384), ("BAAI/bge-base-en-v1.5", 768))
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
TARGET_TOKENS = 400
OVERLAP = 0.12
TOP_K = (1, 5, 10)


@dataclass(frozen=True)
class Chunk:
    """A chunk of one paper with its page range."""

    paper: str
    text: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class Question:
    """A question with its gold snippet and page."""

    paper: str
    question: str
    snippet: str
    page: int


def normalize(text: str) -> str:
    """Lower-case alphanumeric words only, so Markdown and hyphenation differences don't matter."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def page_words(pdf: Path) -> list[tuple[str, int]]:
    """Every word of the PDF with its 1-based page number, parsed as Markdown per page."""
    pages: list[dict[str, Any]] = pymupdf4llm.to_markdown(str(pdf), page_chunks=True)
    words: list[tuple[str, int]] = []
    for number, page in enumerate(pages, start=1):
        words.extend((word, number) for word in str(page["text"]).split())
    return words


def chunk_paper(paper: str, words: list[tuple[str, int]], tokenizer: Any) -> list[Chunk]:
    """Greedy word windows of ~TARGET_TOKENS tokens, each starting ~OVERLAP before the last end."""
    encoded = tokenizer([word for word, _ in words], add_special_tokens=False)
    counts = [len(ids) for ids in encoded["input_ids"]]
    chunks: list[Chunk] = []
    start = 0
    while start < len(words):
        end, tokens = start, 0
        while end < len(words) and tokens + counts[end] <= TARGET_TOKENS:
            tokens += counts[end]
            end += 1
        end = max(end, start + 1)
        window = words[start:end]
        chunks.append(Chunk(paper, " ".join(w for w, _ in window), window[0][1], window[-1][1]))
        if end == len(words):
            break
        back, overlap = end, 0
        while back > start + 1 and overlap < TARGET_TOKENS * OVERLAP:
            back -= 1
            overlap += counts[back]
        start = back
    return chunks


def load_questions(
    path: Path, papers_dir: Path | None = None
) -> tuple[dict[str, Path], list[Question]]:
    """Read a questions file in either supported format.

    - `.json`: `papers` (id + file, relative to the questions file) and `questions`.
    - `.jsonl`: one question per line with `doc` (a PDF name in `papers_dir`), `question`,
      `snippet`, and `page`.
    """
    if path.suffix == ".jsonl":
        if papers_dir is None:
            raise SystemExit("--papers-dir is required for a .jsonl questions file")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        papers = {row["doc"]: papers_dir / row["doc"] for row in rows}
        return papers, [
            Question(r["doc"], r["question"], r["snippet"], int(r["page"])) for r in rows
        ]
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = {paper["id"]: path.parent / paper["file"] for paper in data["papers"]}
    questions = [
        Question(q["paper"], q["question"], q["snippet"], int(q["page"])) for q in data["questions"]
    ]
    return papers, questions


def first_hit(ranked: list[Chunk], question: Question, strict: bool) -> int | None:
    """1-based rank of the first hit, or None."""
    snippet = normalize(question.snippet)
    for rank, chunk in enumerate(ranked, start=1):
        if chunk.paper != question.paper:
            continue
        if snippet in normalize(chunk.text) or (
            not strict and chunk.page_start <= question.page <= chunk.page_end
        ):
            return rank
    return None


def metrics(ranks: list[int | None]) -> dict[str, float]:
    """Recall@k and MRR over all questions."""
    result = {f"R@{k}": sum(r is not None and r <= k for r in ranks) / len(ranks) for k in TOP_K}
    result["MRR"] = sum(1 / r for r in ranks if r is not None) / len(ranks)
    return result


async def evaluate(
    model_id: str, dimension: int, chunks: list[Chunk], questions: list[Question]
) -> tuple[list[int | None], list[int | None], float]:
    """Embed chunks and questions with one model; return strict and lenient ranks and time."""
    embedder = SentenceTransformerEmbedder(
        model_id=model_id,
        dimension=dimension,
        query_prefix=QUERY_PREFIX,
        batch_size=16,
        inference=LocalInference(1),
    )
    embedder.load()
    started = time.perf_counter()
    chunk_vectors = await embedder.embed_documents([chunk.text for chunk in chunks])
    seconds = time.perf_counter() - started
    strict_ranks, lenient_ranks = [], []
    for question in questions:
        query = await embedder.embed_query(question.question)
        scores = [sum(a * b for a, b in zip(query, v, strict=True)) for v in chunk_vectors]
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
        ranked = [chunks[i] for i in order[: max(TOP_K)]]
        strict_ranks.append(first_hit(ranked, question, strict=True))
        lenient_ranks.append(first_hit(ranked, question, strict=False))
    return strict_ranks, lenient_ranks, seconds


async def run(args: argparse.Namespace) -> None:
    """Chunk the papers once, check the gold snippets, and compare the models."""
    from transformers import AutoTokenizer

    papers, questions = load_questions(args.questions, args.papers_dir)
    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_MODELS[0][0])
    chunks = [
        chunk
        for paper, pdf in papers.items()
        for chunk in chunk_paper(paper, page_words(pdf), tokenizer)
    ]
    print(f"{len(papers)} papers, {len(chunks)} chunks, {len(questions)} questions")
    for question in questions:
        if not any(
            c.paper == question.paper and normalize(question.snippet) in normalize(c.text)
            for c in chunks
        ):
            print(f"warning: snippet not found in any chunk: {question.snippet[:60]!r}")

    header = " | ".join(f"{name}" for name in [*(f"R@{k}" for k in TOP_K), "MRR"])
    print(f"\n| Model | Match | {header} | Embed {len(chunks)} chunks (s) |")
    print("|---|---|" + "---|" * (len(TOP_K) + 2))
    results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for model_id, dimension in DEFAULT_MODELS:
        strict, lenient, seconds = await evaluate(model_id, dimension, chunks, questions)
        summary[model_id] = {
            "snippet": metrics(strict),
            "page": metrics(lenient),
            "embed_seconds": round(seconds, 2),
        }
        for label in ("snippet", "page"):
            cells = " | ".join(f"{value:.2f}" for value in summary[model_id][label].values())
            print(f"| {model_id} | {label} | {cells} | {seconds:.1f} |", flush=True)
        results.extend(
            {
                "model": model_id,
                "paper": question.paper,
                "question": question.question,
                "gold_page": question.page,
                "rank_snippet": rank_snippet,
                "rank_page": rank_page,
            }
            for question, rank_snippet, rank_page in zip(questions, strict, lenient, strict=True)
        )
    path = write_experiment(
        "compare_embeddings",
        settings=get_settings(),
        models={"embedding": [model_id for model_id, _ in DEFAULT_MODELS]},
        dataset=args.questions.name,
        parameters={
            "target_tokens": TARGET_TOKENS,
            "overlap": OVERLAP,
            "top_k": list(TOP_K),
            "papers": len(papers),
            "chunks": len(chunks),
            "questions": len(questions),
        },
        results=results,
        summary=summary,
    )
    print(f"\nWrote {path}")


def main() -> None:
    """Parse arguments and run the comparison."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, required=True, help=".json or .jsonl file")
    parser.add_argument("--papers-dir", type=Path, help="PDF folder for a .jsonl questions file")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
