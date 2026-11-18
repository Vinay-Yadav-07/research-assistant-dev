"""Quality check: Recall@5 after hybrid retrieval + RRF + rerank, for two rerankers (D-051).

Run from `backend/`:
    uv run python -m scripts.compare_rerankers \\
        --questions scripts/data/embedding_comparison/questions.json
    uv run python -m scripts.compare_rerankers --questions scripts/data/embedding_check_v1.jsonl \\
        --papers-dir scripts/data/papers

Mirrors the SRS §8.2 pipeline in memory: dense (the default embedding model) top 30 and BM25 top
30 over all papers' chunks, fused with Reciprocal Rank Fusion, the top `--candidates` reranked.
BM25 stands in for Postgres full-text search. Chunks and hit rules are those of
`scripts.compare_embeddings`. With ~15 questions per set only large differences mean anything.
"""

import argparse
import asyncio
import math
import re
import time
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.providers.local import CrossEncoderReranker, LocalInference, SentenceTransformerEmbedder
from scripts.compare_embeddings import (
    QUERY_PREFIX,
    Chunk,
    Question,
    chunk_paper,
    first_hit,
    load_questions,
    page_words,
)
from scripts.experiment_log import write_experiment

RERANKERS = ("BAAI/bge-reranker-base", "cross-encoder/ms-marco-MiniLM-L-6-v2")
SEARCH_TOP = 30
RRF_K = 60
RECALL_AT = 5


def terms(text: str) -> list[str]:
    """Lower-case word tokens for BM25."""
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_ranking(query: str, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[int]:
    """Indices of `docs` ordered by BM25 score for `query` (only docs sharing a term)."""
    avg_len = sum(len(doc) for doc in docs) / len(docs)
    df = Counter(term for doc in docs for term in set(doc))
    scores: dict[int, float] = {}
    for index, doc in enumerate(docs):
        counts = Counter(doc)
        score = 0.0
        for term in set(terms(query)):
            if term in counts:
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                tf = counts[term]
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / avg_len))
        if score > 0:
            scores[index] = score
    return sorted(scores, key=lambda i: scores[i], reverse=True)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    """Reciprocal Rank Fusion of several rankings of the same items."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1 / (k + rank)
    return sorted(fused, key=lambda i: fused[i], reverse=True)


def recall(ranked_lists: list[list[Chunk]], questions: list[Question], strict: bool) -> float:
    """Share of questions with a hit in the top RECALL_AT."""
    hits = [
        first_hit(ranked[:RECALL_AT], q, strict)
        for ranked, q in zip(ranked_lists, questions, strict=True)
    ]
    return sum(hit is not None for hit in hits) / len(questions)


async def run(args: argparse.Namespace) -> None:
    """Retrieve and fuse once, then rerank the same candidates with each reranker."""
    settings = get_settings()
    papers, questions = load_questions(args.questions, args.papers_dir)
    embedder = SentenceTransformerEmbedder(
        model_id=args.embedding_model,
        dimension=args.embedding_dimension,
        query_prefix=QUERY_PREFIX,
        batch_size=16,
        inference=LocalInference(1),
    )
    embedder.load()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.embedding_model)
    chunks = [
        chunk
        for paper, pdf in papers.items()
        for chunk in chunk_paper(paper, page_words(pdf), tokenizer)
    ]
    vectors = await embedder.embed_documents([chunk.text for chunk in chunks])
    docs = [terms(chunk.text) for chunk in chunks]

    candidates: list[list[int]] = []
    for question in questions:
        query = await embedder.embed_query(question.question)
        scores = [sum(a * b for a, b in zip(query, v, strict=True)) for v in vectors]
        dense = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:SEARCH_TOP]
        lexical = bm25_ranking(question.question, docs)[:SEARCH_TOP]
        candidates.append(rrf([dense, lexical])[: args.candidates])

    print(
        f"{args.questions.name}: {len(papers)} papers, {len(chunks)} chunks, "
        f"{len(questions)} questions; {args.embedding_model}; {args.candidates} candidates\n"
    )
    print(f"| Stage | R@{RECALL_AT} snippet | R@{RECALL_AT} page | Rerank time per question (s) |")
    print("|---|---|---|---|")
    fused = [[chunks[i] for i in c] for c in candidates]
    results = [
        {
            "paper": q.paper,
            "question": q.question,
            "gold_page": q.page,
            "rrf": ranks(pool, q),
        }
        for q, pool in zip(questions, fused, strict=True)
    ]
    summary: dict[str, dict[str, float]] = {
        "rrf": {
            "recall_snippet": recall(fused, questions, True),
            "recall_page": recall(fused, questions, False),
        }
    }
    print(
        f"| RRF only | {summary['rrf']['recall_snippet']:.2f} | "
        f"{summary['rrf']['recall_page']:.2f} | – |"
    )

    for model_id in RERANKERS:
        reranker = CrossEncoderReranker(
            model_id=model_id,
            max_length=settings.reranker_max_length,
            batch_size=16,
            inference=LocalInference(1),
        )
        reranker.load()
        reranked, seconds = [], 0.0
        for question, pool, row in zip(questions, fused, results, strict=True):
            started = time.perf_counter()
            scores = await reranker.score(question.question, [chunk.text for chunk in pool])
            elapsed = time.perf_counter() - started
            seconds += elapsed
            order = sorted(range(len(pool)), key=lambda i: scores[i], reverse=True)
            reranked.append([pool[i] for i in order])
            row[model_id] = {**ranks(reranked[-1], question), "rerank_ms": round(elapsed * 1000)}
        summary[model_id] = {
            "recall_snippet": recall(reranked, questions, True),
            "recall_page": recall(reranked, questions, False),
            "rerank_seconds_per_question": round(seconds / len(questions), 2),
        }
        print(
            f"| {model_id} | {summary[model_id]['recall_snippet']:.2f} | "
            f"{summary[model_id]['recall_page']:.2f} | {seconds / len(questions):.1f} |",
            flush=True,
        )

    path = write_experiment(
        "compare_rerankers",
        settings=settings,
        models={"embedding": args.embedding_model, "rerankers": list(RERANKERS)},
        dataset=args.questions.name,
        parameters={
            "search_top": SEARCH_TOP,
            "rrf_k": RRF_K,
            "candidates": args.candidates,
            "recall_at": RECALL_AT,
            "lexical": "in-memory BM25",
            "papers": len(papers),
            "chunks": len(chunks),
            "questions": len(questions),
        },
        results=results,
        summary=summary,
    )
    print(f"\nWrote {path}")


def ranks(ranked: list[Chunk], question: Question) -> dict[str, int | None]:
    """1-based rank of the first snippet hit and the first page hit, or None."""
    return {
        "rank_snippet": first_hit(ranked, question, True),
        "rank_page": first_hit(ranked, question, False),
    }


def main() -> None:
    """Parse arguments and run the comparison."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, required=True, help=".json or .jsonl file")
    parser.add_argument("--papers-dir", type=Path, help="PDF folder for a .jsonl questions file")
    parser.add_argument("--candidates", type=int, default=20, help="fused candidates to rerank")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--embedding-dimension", type=int, default=384)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
