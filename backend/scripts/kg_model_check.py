"""Structured-output check of a candidate graph-tier model (SRS §9.1 model criteria, D-083).

Reads batches of passages from the given papers on the configured database (read only), sends
each batch to the candidate model once (no retry, so first-attempt validity is what is
measured), validates every reply with the real evidence rules and the local NLI model, and
writes one experiment JSON to `docs/experiments/`. Nothing is written to the database.

Makes real LLM calls (at most `--batches` batches, `--max-requests` requests including
retries, and about `--max-tokens` tokens), so run it only when the team has approved them:
    uv run python -m scripts.kg_model_check --provider gemini --model MODEL_ID \\
        --document UUID --document UUID --document UUID --batches 20

`--list-models` prints the Gemini API model names containing "gemma" (one free listing request).
"""

import argparse
import asyncio
import math
import statistics
import time
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import LLMOutputError, LLMProviderError, LLMQuotaExceededError
from app.models.document import Document
from app.prompts import load_prompt
from app.providers.factory import build_graph_llm, build_nli
from app.providers.llm import ChatMessage
from app.providers.local.runtime import LocalInference
from app.providers.usage import RunUsage, track_usage
from app.repositories.chunks import ChunkRecord
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.repositories.knowledge_graph import KnowledgeGraphRepository
from app.services.citations import CitationService
from app.services.knowledge_graph import (
    EXTRACTOR_VERSION,
    PROMPT_VERSION,
    KGBatchExtraction,
    KGExtractionOptions,
    KnowledgeGraphExtractor,
    batch_request,
    batches,
    is_review,
    select_chunks,
)
from scripts.experiment_log import snippet, write_experiment

# A batch counts as valid only if the reply validates on the first attempt (criterion 1).
PASS_VALID_BATCHES = 19 / 20
# Stop after this many batches fail with provider outages, so an overloaded model costs little.
MAX_UNAVAILABLE = 2
# Rough token estimate before the provider reports usage (as in the provider).
CHARS_PER_TOKEN = 4


def spent_tokens(usage: RunUsage, failed_attempt_tokens: int) -> int:
    """Tokens reported by the provider, plus a worst-case estimate for every failed attempt
    (providers do not report usage for rejected replies, but may still count it)."""
    return usage.total_tokens + usage.failed_attempts * failed_attempt_tokens


def spread(groups: list[list[ChunkRecord]], count: int) -> list[list[ChunkRecord]]:
    """`count` batches spread evenly over the paper, so every part of it is sampled."""
    if count >= len(groups):
        return groups
    step = len(groups) / count
    return [groups[math.floor(n * step)] for n in range(count)]


async def load_papers(
    settings: Settings, document_ids: list[UUID], options: KGExtractionOptions
) -> tuple[list[tuple[Document, list[list[ChunkRecord]]]], dict[UUID, ChunkRecord], set[UUID]]:
    """Each paper and its batches, read as its owner, and each passage's predecessor."""
    engine = create_engine_from_settings(settings)
    if engine is None:
        raise SystemExit("DATABASE_URL is not set")
    papers = []
    previous: dict[UUID, ChunkRecord] = {}
    reviews: set[UUID] = set()
    try:
        async with create_sessionmaker(engine)() as session:
            repository = KnowledgeGraphRepository(session)
            for document_id in document_ids:
                document = await session.scalar(select(Document).where(Document.id == document_id))
                if document is None or document.status != "ready":
                    raise SystemExit(f"Document {document_id} is missing or not ready")
                chunks = await repository.document_chunks(document.user_id, document_id)
                previous.update({b.chunk_id: a for a, b in zip(chunks, chunks[1:], strict=False)})
                if is_review(chunks):
                    reviews.add(document_id)
                selected = select_chunks(chunks, options)
                papers.append((document, batches(selected, options.chunks_per_call)))
    finally:
        await engine.dispose()
    return papers, previous, reviews


async def check(args: argparse.Namespace) -> None:
    settings = Settings().model_copy(
        update={"llm_graph_provider": args.provider, "llm_graph_model": args.model}
    )
    options = KGExtractionOptions.from_settings(settings)
    llm = build_graph_llm(settings)
    nli = build_nli(settings, LocalInference(settings.local_inference_concurrency))
    extractor = KnowledgeGraphExtractor(llm, nli, CitationService.from_settings(settings), options)
    papers, previous, reviews = await load_papers(settings, args.document, options)
    per_paper = math.ceil(args.batches / len(papers))
    sample = [
        (document, group) for document, groups in papers for group in spread(groups, per_paper)
    ][: args.batches]
    system = load_prompt("services", "kg_extraction", PROMPT_VERSION)
    attempts_per_batch = settings.llm_graph_max_retries + 1

    results: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    stopped: str | None = None
    unavailable = 0
    worst_call = 0
    with track_usage() as usage:
        for number, (document, group) in enumerate(sample):
            messages = [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=batch_request(group)),
            ]
            # Budgets are checked against the batch's worst case (every retry, full output).
            worst_call = (
                sum(len(m.content) for m in messages) // CHARS_PER_TOKEN + options.max_output_tokens
            )
            if usage.calls + usage.failed_attempts + attempts_per_batch > args.max_requests:
                stopped = "request_budget"
                print(f"batch {number}: request budget ({args.max_requests}) reached; stopping")
                break
            if spent_tokens(usage, worst_call) + attempts_per_batch * worst_call > args.max_tokens:
                stopped = "token_budget"
                print(f"batch {number}: token budget ({args.max_tokens}) reached; stopping")
                break
            started = time.perf_counter()
            row: dict[str, Any] = {"batch": number, "document_id": str(document.id)}
            try:
                reply = await llm.generate_structured(
                    messages,
                    KGBatchExtraction,
                    temperature=0,
                    max_output_tokens=options.max_output_tokens,
                )
            except LLMOutputError as error:
                # Which fields failed, never the reply itself (it holds paper text).
                row.update(
                    valid=False,
                    seconds=round(time.perf_counter() - started, 2),
                    errors=[
                        {"loc": e.get("loc"), "type": e.get("type")}
                        for e in error.details.get("errors", [])
                    ][:20],
                )
                results.append(row)
                print(f"batch {number}: invalid output: {row['errors'][:3]}")
                continue
            except LLMQuotaExceededError:
                stopped = "llm_quota_exhausted"
                print(f"batch {number}: daily quota used up; stopping")
                break
            except LLMProviderError as error:
                # Outages (e.g. 503) say nothing about structured output; not counted as answers.
                unavailable += 1
                cause = error.__cause__
                print(f"batch {number}: provider error after retries ({type(cause).__name__})")
                if unavailable >= MAX_UNAVAILABLE:
                    stopped = "provider_unavailable"
                    print("provider keeps failing; stopping")
                    break
                continue
            seconds = round(time.perf_counter() - started, 2)
            kept = await extractor.validate(
                document.id,
                group,
                reply.output,
                prefix=f"b{number}",
                previous=previous,
                review=document.id in reviews,
            )
            rejected.update(kept.rejected)
            names = {m.key: m.surface_text for m in kept.entities}
            row.update(
                valid=True,
                seconds=seconds,
                input_tokens=reply.usage.input_tokens,
                output_tokens=reply.usage.output_tokens,
                entities_proposed=len(reply.output.entities),
                relations_proposed=len(reply.output.relations),
                entities_kept=len(kept.entities),
                relations_kept=[
                    {
                        "type": r.relation_type,
                        "source": snippet(names[r.source_key]),
                        "target": snippet(names[r.target_key]),
                        "quote": snippet(r.quote),
                        "entailment": round(r.entailment_score, 3),
                    }
                    for r in kept.relations
                ],
                rejected=dict(kept.rejected),
            )
            results.append(row)
            print(
                f"batch {number}: {len(reply.output.relations)} proposed, "
                f"{len(kept.relations)} kept, {seconds} s"
            )
        requests_made = usage.calls + usage.failed_attempts
        failed_attempts = usage.failed_attempts
        tokens_counted = spent_tokens(usage, worst_call)

    answered = [r for r in results if r["valid"]]
    valid = len(answered)
    batches_per_paper = statistics.mean(len(groups) for _, groups in papers)
    summary = {
        "batches_sent": len(results),
        "valid_first_attempt": valid,
        "passes_structured_output": len(results) > 0
        and valid >= math.ceil(PASS_VALID_BATCHES * len(results)),
        "stopped": stopped,
        "batches_unavailable": unavailable,
        "requests_made": requests_made,
        "failed_attempts": failed_attempts,
        "tokens_counted_against_budget": tokens_counted,
        "input_tokens": sum(r["input_tokens"] for r in answered),
        "output_tokens": sum(r["output_tokens"] for r in answered),
        "mean_tokens_per_call": round(
            statistics.mean(r["input_tokens"] + r["output_tokens"] for r in answered), 1
        )
        if answered
        else None,
        "median_seconds": statistics.median(r["seconds"] for r in answered) if answered else None,
        "max_seconds": max((r["seconds"] for r in answered), default=None),
        "relations_proposed": sum(r["relations_proposed"] for r in answered),
        "relations_kept": sum(len(r["relations_kept"]) for r in answered),
        "entities_kept": sum(r["entities_kept"] for r in answered),
        "rejected": dict(rejected),
        "mean_batches_per_paper": round(batches_per_paper, 1),
        "estimated_calls_per_10_papers": math.ceil(10 * batches_per_paper),
    }
    path = write_experiment(
        "kg_model_check",
        settings=settings,
        models={"graph_llm": f"{args.provider}:{args.model}", "nli": settings.nli_model},
        dataset="; ".join(snippet(document.title or str(document.id)) for document, _ in papers),
        results=results,
        summary=summary,
        parameters={
            "batches": args.batches,
            "max_requests": args.max_requests,
            "max_tokens": args.max_tokens,
            "extractor_version": EXTRACTOR_VERSION,
        },
        secrets=[
            key.get_secret_value()
            for key in (settings.llm_graph_api_key, settings.gemini_api_key, settings.groq_api_key)
            if key is not None
        ],
    )
    print(
        f"{valid}/{len(results)} valid on the first attempt; {requests_made} requests, "
        f"{tokens_counted} tokens counted; report: {path}"
    )


def list_models() -> None:
    from google import genai

    key = Settings().gemini_api_key
    if key is None:
        raise SystemExit("GEMINI_API_KEY is not set")
    # Keep the client referenced: the pager fetches further pages through it.
    client = genai.Client(api_key=key.get_secret_value())
    for model in client.models.list():
        if model.name and "gemma" in model.name:
            print(model.name, model.supported_actions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--provider", choices=["groq", "gemini"])
    parser.add_argument("--model")
    parser.add_argument("--document", type=UUID, action="append", default=[])
    parser.add_argument("--batches", type=int, default=20)
    # Hard caps for the whole run, checked before each batch against its worst case.
    parser.add_argument("--max-requests", type=int, default=25)
    parser.add_argument("--max-tokens", type=int, default=100_000)
    args = parser.parse_args()
    if args.list_models:
        list_models()
        return
    if not (args.provider and args.model and args.document):
        parser.error("--provider, --model and at least one --document are required")
    asyncio.run(check(args))


if __name__ == "__main__":
    main()
