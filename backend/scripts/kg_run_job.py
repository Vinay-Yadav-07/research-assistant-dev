"""Run one knowledge graph job on a workspace with the real job runner (SRS §9.1, D-085).

Checks first and stops on any failure: the database URL names the expected dev project ref
(the URL is never printed), migration 0008 is applied, the workspace's ready papers are exactly
the expected ones and share its owner, the graph tier is configured with the expected model and
the current extractor version, and the daily request cap (counted in this process for every
attempt, retries included, and fresh at start) is no higher than `--max-requests`.

Without `--start` only the checks run. With it, exactly one job is started and followed until
it ends; it is never retried. Real graph-tier calls, so run it only with approval:
    LLM_GRAPH_PROVIDER=gemini LLM_GRAPH_MODEL=MODEL LLM_GRAPH_RPD=50 KG_MAX_CALLS_PER_JOB=50 \\
    uv run python -m scripts.kg_run_job --dev-ref REF --workspace UUID --model MODEL \\
        --document UUID [--document UUID ...] [--start]
"""

import argparse
import asyncio
import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, text

from app.core.config import Settings
from app.main import build_knowledge_graph
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.knowledge_graph import (
    KGDocumentExtraction,
    KGEntityMention,
    KGRelationMention,
)
from app.models.workspace import Workspace, WorkspaceDocument
from app.providers.factory import build_providers
from app.providers.usage import track_usage
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from app.services.knowledge_graph import EXTRACTOR_VERSION, verbatim_span
from scripts.experiment_log import snippet, write_experiment

MIGRATION = "0008"
POLL_SECONDS = 15
FINISHED = {"completed", "failed"}


def check(label: str, ok: bool, problems: list[str]) -> None:
    print(f"[{'ok' if ok else 'FAIL'}] {label}")
    if not ok:
        problems.append(label)


async def preflight(args: argparse.Namespace, settings: Settings, sessions: Any) -> UUID | None:
    """The workspace owner when every check passes; None (after printing why) otherwise."""
    problems: list[str] = []
    assert settings.database_url is not None
    url = urlsplit(settings.database_url.get_secret_value())
    check(
        "database URL names the dev project ref",
        args.dev_ref in f"{url.username}@{url.hostname}",
        problems,
    )
    async with sessions() as session:
        revision = (await session.execute(text("select version_num from alembic_version"))).scalar()
        check(f"migration {MIGRATION} applied (found {revision})", revision == MIGRATION, problems)
        workspace = await session.get(Workspace, args.workspace)
        check("workspace exists", workspace is not None, problems)
        if workspace is None:
            return None
        rows = (
            await session.execute(
                select(Document.id, Document.user_id)
                .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
                .where(WorkspaceDocument.workspace_id == args.workspace, Document.status == "ready")
            )
        ).all()
        ready = {row.id for row in rows}
        check(
            f"workspace's ready papers are exactly the {len(args.document)} expected "
            f"(found {len(ready)}, {len(ready & set(args.document))} expected)",
            ready == set(args.document),
            problems,
        )
        check(
            "papers share the workspace owner",
            all(r.user_id == workspace.user_id for r in rows),
            problems,
        )
    check(
        f"graph tier {settings.llm_graph_provider}:{settings.llm_graph_model}",
        settings.llm_graph_provider != "fake" and settings.llm_graph_model == args.model,
        problems,
    )
    check(
        f"extractor {EXTRACTOR_VERSION}", EXTRACTOR_VERSION == "kg-extraction.v2+rules.v3", problems
    )
    check(
        f"request cap: LLM_GRAPH_RPD={settings.llm_graph_rpd} <= {args.max_requests} "
        f"(every attempt, retries included), KG_MAX_CALLS_PER_JOB={settings.kg_max_calls_per_job}",
        0 < settings.llm_graph_rpd <= args.max_requests
        and settings.kg_max_calls_per_job <= args.max_requests,
        problems,
    )
    print(
        f"[info] limits {settings.llm_graph_rpm} RPM / {settings.llm_graph_tpm} TPM; retries "
        f"{settings.llm_graph_max_retries} from {settings.llm_graph_retry_base_seconds}s"
    )
    return None if problems else workspace.user_id


async def report(sessions: Any, job_id: UUID, workspace_id: UUID) -> dict[str, Any]:
    """Per-paper extractions, rejections, counts, and whether every quote is verbatim."""
    async with sessions() as session:
        extractions = (
            await session.execute(
                select(KGDocumentExtraction, Document.title)
                .join(Document, Document.id == KGDocumentExtraction.document_id)
                .join(WorkspaceDocument, WorkspaceDocument.document_id == Document.id)
                .where(
                    WorkspaceDocument.workspace_id == workspace_id,
                    KGDocumentExtraction.extractor_version == EXTRACTOR_VERSION,
                )
            )
        ).all()
        papers, rejected = [], Counter[str]()
        relations: list[dict[str, Any]] = []
        quotes_ok = quotes_bad = 0
        for extraction, title in extractions:
            entities = await session.scalar(
                select(func.count()).where(KGEntityMention.extraction_id == extraction.id)
            )
            rows = (
                await session.execute(
                    select(KGRelationMention, Chunk.text, Chunk.document_id)
                    .join(Chunk, Chunk.id == KGRelationMention.chunk_id)
                    .where(KGRelationMention.extraction_id == extraction.id)
                )
            ).all()
            for mention, chunk_text, chunk_document in rows:
                ok = (
                    chunk_document == mention.document_id
                    and verbatim_span(mention.quote, chunk_text) is not None
                )
                quotes_ok, quotes_bad = quotes_ok + ok, quotes_bad + (not ok)
                source = await session.get(KGEntityMention, mention.source_mention_id)
                target = await session.get(KGEntityMention, mention.target_mention_id)
                assert source is not None and target is not None
                relations.append(
                    {
                        "paper": snippet(title or ""),
                        "type": mention.relation_type,
                        "source": f"{source.surface_text} ({source.entity_type})",
                        "target": f"{target.surface_text} ({target.entity_type})",
                        "quote": mention.quote,
                        "entailment": round(mention.entailment_score, 3),
                        "quote_verbatim": ok,
                    }
                )
            rejected.update(extraction.rejected_counts)
            papers.append(
                {
                    "paper": snippet(title or ""),
                    "status": extraction.status,
                    "chunks_considered": extraction.chunks_considered,
                    "llm_calls": extraction.llm_calls,
                    "tokens": extraction.tokens,
                    "entities": entities,
                    "relations": len(rows),
                    "rejected": extraction.rejected_counts,
                }
            )
        graph = (
            await session.execute(
                text("select node_count, edge_count from kg_graphs where workspace_id = :w"),
                {"w": workspace_id},
            )
        ).first()
    return {
        "papers": papers,
        "rejected_total": dict(rejected.most_common()),
        "graph": dict(graph._mapping) if graph else None,
        "quotes_verbatim": quotes_ok,
        "quotes_not_verbatim": quotes_bad,
        "relations": relations,
    }


async def main_async(args: argparse.Namespace) -> None:
    settings = Settings()
    engine = create_engine_from_settings(settings)
    if engine is None:
        raise SystemExit("DATABASE_URL is not set")
    sessions = create_sessionmaker(engine)
    try:
        owner = await preflight(args, settings, sessions)
        if owner is None:
            raise SystemExit("Preflight failed; no job started.")
        if not args.start:
            print("Preflight passed; add --start to run the job.")
            return
        runner = build_knowledge_graph(settings, build_providers(settings), sessions)
        started = time.perf_counter()
        with track_usage() as usage:
            job, _ = await runner.start(owner, args.workspace)
            while job.status not in FINISHED:
                await asyncio.sleep(POLL_SECONDS)
                job = await runner.get_job(owner, args.workspace, job.id)
                print(
                    f"{time.perf_counter() - started:6.0f}s {job.status} {job.phase} "
                    f"{job.documents_done}/{job.documents_total} papers, "
                    f"{usage.calls} calls, {usage.failed_attempts} failed attempts"
                )
        seconds = round(time.perf_counter() - started, 1)
        summary = {
            "job_status": job.status,
            "error_code": job.error_code,
            "seconds": seconds,
            "provider_requests": usage.calls + usage.failed_attempts,
            "successful_calls": usage.calls,
            "failed_attempts": usage.failed_attempts,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        details = await report(sessions, job.id, args.workspace)
        relations = details.pop("relations")
        summary |= details
        print(summary)
        write_experiment(
            "kg_run_job",
            settings=settings,
            models={"graph_llm": f"{settings.llm_graph_provider}:{settings.llm_graph_model}"},
            dataset=f"workspace {args.workspace} ({len(args.document)} papers, dev)",
            results=relations,
            summary=summary,
            parameters={"extractor_version": EXTRACTOR_VERSION, "max_requests": args.max_requests},
            secrets=[
                key.get_secret_value()
                for key in (
                    settings.llm_graph_api_key,
                    settings.gemini_api_key,
                    settings.database_url,
                )
                if key is not None
            ],
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-ref", required=True, help="Supabase dev project ref")
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--document", type=UUID, action="append", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-requests", type=int, default=50)
    parser.add_argument("--start", action="store_true", help="run the job (real LLM calls)")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
