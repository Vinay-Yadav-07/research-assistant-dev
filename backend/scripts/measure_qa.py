"""Measure grounded Q&A over the public API: NFR-01 latency and NFR-13 LLM calls per question.

Run from `backend/` against a running backend, e.g. the Space, with `DATABASE_URL` pointing at
the database that backend uses (the LLM call counts are read from its `agent_runs`):
    MEASURE_TOKEN=<access token> DATABASE_URL="$PROD_DB" uv run python -m scripts.measure_qa \\
        --base-url https://<space>.hf.space --server-hardware "HF Spaces cpu-basic (2 vCPU)"

For each corpus the questions need, creates a workspace, uploads the corpus PDFs, and waits until
they are `ready`. Then asks each benchmark question in a new conversation and reads the SSE
stream: time to the first event, total time, outcome, and the claims and citations sent. A run
that pauses for approval (S4) is resumed at once with `corpus_only`; the time spent waiting for
the human is not counted. Run stats (status, LLM calls, tokens) come from `agent_runs`, read as
the token's user. The workspaces are always deleted afterwards. Writes the experiment JSON; the
access token and the database URL are never written.
"""

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.repositories.conversations import ConversationRepository
from app.repositories.database import create_engine_from_settings, create_sessionmaker
from eval.dataset import BenchmarkItem, load_corpora, load_items
from eval.metrics import percentile
from scripts.experiment_log import secret_values, write_experiment

API = "/api/v1"
FINAL_DOCUMENT_STATUSES = ("ready", "failed")
# A stratified sample of the test split (D-071): 7 single, 2 multi, 1 comparison,
# 2 unanswerable, over both corpora. Phase 8 measures the full benchmark.
SAMPLE_IDS = (
    "test-001",
    "test-008",
    "test-014",
    "test-020",
    "test-025",
    "test-031",
    "test-033",
    "test-039",
    "test-042",
    "test-038",
    "test-046",
    "test-051",
)
NFR_01_FIRST_EVENT_SECONDS = 2.0
NFR_01_P50_SECONDS = 25.0
NFR_01_P90_SECONDS = 45.0
NFR_13_MEAN_LLM_CALLS = 10.0


class MeasurementError(RuntimeError):
    """The measurement could not be made (API error, ingestion failure, timeout, missing run)."""


@dataclass(frozen=True)
class RunStats:
    """A run's cost summary from `agent_runs`."""

    status: str
    llm_calls: int
    tokens: int
    latency_ms: int | None


RunReader = Callable[[Sequence[UUID]], Awaitable[dict[UUID, RunStats]]]


@dataclass
class Stream:
    """The events of one SSE response; times are seconds since the request was sent."""

    events: list[dict[str, Any]]
    first_event_seconds: float | None
    seconds: float


@dataclass
class ItemMeasurement:
    """One question: what the stream showed and, once read, its run stats."""

    item: BenchmarkItem
    first_event_seconds: float | None
    ask_seconds: float
    resume_seconds: float | None = None
    run_id: UUID | None = None
    outcome: str | None = None
    claims: int = 0
    citations: int = 0
    error: str | None = None
    stages: list[str] = field(default_factory=list)
    run: RunStats | None = None

    @property
    def paused(self) -> bool:
        """True if the run asked for approval and was resumed."""
        return self.resume_seconds is not None

    @property
    def total_seconds(self) -> float:
        """Answer time without the approval wait: the ask stream plus the resume stream."""
        return self.ask_seconds + (self.resume_seconds or 0.0)

    @property
    def correct(self) -> bool:
        """Answerable questions should be answered, unanswerable ones abstained."""
        expected = "answered" if self.item.answerable else "abstained"
        return self.outcome == expected


def check(response: httpx.Response, action: str) -> httpx.Response:
    """Raise `MeasurementError` with the API error body unless the response is 2xx."""
    if response.is_success:
        return response
    raise MeasurementError(f"{action} failed: HTTP {response.status_code} {response.text[:300]}")


async def stream_events(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> Stream:
    """POST and read the whole SSE stream; keepalive comments are skipped."""
    started = clock()
    first: float | None = None
    events: list[dict[str, Any]] = []
    async with client.stream("POST", path, json=body) as response:
        if not response.is_success:
            await response.aread()
            check(response, f"POST {path}")
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            if first is None:
                first = clock() - started
            events.append(json.loads(line.removeprefix("data:").strip()))
    return Stream(events, first, clock() - started)


async def create_workspace(client: httpx.AsyncClient, corpus: str) -> str:
    """A new corpus-only workspace for one corpus; returns its id."""
    created = check(
        await client.post(
            f"{API}/workspaces",
            json={"name": f"QA measurement: {corpus}", "default_mode": "corpus_only"},
        ),
        "create workspace",
    )
    return str(created.json()["id"])


async def upload_and_wait(
    client: httpx.AsyncClient,
    workspace_id: str,
    papers: Sequence[Path],
    *,
    poll_seconds: float,
    timeout_seconds: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Upload every paper (linking any the user already has) and wait until all are `ready`."""
    documents: dict[str, str] = {}
    for path in papers:
        data = await asyncio.to_thread(path.read_bytes)
        upload = check(
            await client.post(
                f"{API}/workspaces/{workspace_id}/documents",
                files={"file": (path.name, data, "application/pdf")},
                data={"override": "true"},
            ),
            f"upload {path.name}",
        ).json()
        documents[path.name] = upload["document"]["id"]
    started = clock()
    pending = dict(documents)
    while pending:
        for name, document_id in list(pending.items()):
            document = check(
                await client.get(f"{API}/documents/{document_id}"), f"get {name}"
            ).json()
            if document["status"] == "failed":
                raise MeasurementError(f"{name} failed to ingest: {document['error']}")
            if document["status"] == "ready":
                del pending[name]
        if not pending:
            return
        if clock() - started > timeout_seconds:
            raise MeasurementError(f"not ready after {timeout_seconds:.0f} s: {sorted(pending)}")
        await sleep(poll_seconds)


def _apply(result: ItemMeasurement, events: list[dict[str, Any]]) -> UUID | None:
    """Record the stream's events; return the run id if the run paused for approval."""
    for event in events:
        match event["type"]:
            case "status":
                result.stages.append(event["stage"])
            case "approval_required":
                result.run_id = UUID(event["run_id"])
                return result.run_id
            case "claims":
                result.claims = len(event["claims"])
            case "citations":
                result.citations = len(event["citations"])
            case "error":
                result.run_id = UUID(event["run_id"])
                result.error = f"{event['code']}: {event['message']}"
            case "done":
                result.run_id = UUID(event["run_id"])
                result.outcome = event["outcome"]
    return None


async def ask(
    client: httpx.AsyncClient,
    workspace_id: str,
    item: BenchmarkItem,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> ItemMeasurement:
    """Ask one question in a new conversation; resume with `corpus_only` if it pauses."""
    conversation = check(
        await client.post(
            f"{API}/workspaces/{workspace_id}/conversations", json={"title": item.id}
        ),
        "create conversation",
    ).json()
    asked = await stream_events(
        client,
        f"{API}/conversations/{conversation['id']}/messages",
        {"content": item.question},
        clock=clock,
    )
    result = ItemMeasurement(
        item=item, first_event_seconds=asked.first_event_seconds, ask_seconds=asked.seconds
    )
    paused = _apply(result, asked.events)
    if paused is not None:
        resumed = await stream_events(
            client, f"{API}/runs/{paused}/resume", {"decision": "corpus_only"}, clock=clock
        )
        result.resume_seconds = resumed.seconds
        _apply(result, resumed.events)
    return result


async def measure(
    client: httpx.AsyncClient,
    items: Sequence[BenchmarkItem],
    corpora: dict[str, list[Path]],
    read_runs: RunReader,
    *,
    poll_seconds: float,
    timeout_seconds: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[ItemMeasurement]:
    """Ingest the needed corpora, ask every item, read the run stats, delete the workspaces.

    Run stats are read before the workspaces are deleted, since deleting removes their runs.
    """
    workspaces: dict[str, str] = {}
    try:
        for corpus in dict.fromkeys(item.corpus for item in items):
            workspaces[corpus] = await create_workspace(client, corpus)
            await upload_and_wait(
                client,
                workspaces[corpus],
                corpora[corpus],
                poll_seconds=poll_seconds,
                timeout_seconds=timeout_seconds,
                clock=clock,
                sleep=sleep,
            )
        results = []
        for item in items:
            result = await ask(client, workspaces[item.corpus], item, clock=clock)
            print(f"{item.id}: {result.outcome or result.error} in {result.total_seconds:.1f} s")
            results.append(result)
        stats = await read_runs([r.run_id for r in results if r.run_id is not None])
        for result in results:
            result.run = None if result.run_id is None else stats.get(result.run_id)
        return results
    finally:
        for workspace_id in workspaces.values():
            check(await client.delete(f"{API}/workspaces/{workspace_id}"), "delete workspace")


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def summarize(results: Sequence[ItemMeasurement]) -> dict[str, Any]:
    """Latency, cost, and outcome figures against NFR-01 and NFR-13."""
    totals = [r.total_seconds for r in results]
    answered = [r for r in results if r.outcome == "answered"]
    answered_totals = [r.total_seconds for r in answered]
    firsts = [r.first_event_seconds for r in results if r.first_event_seconds is not None]
    runs = [r.run for r in results if r.run is not None]
    calls = [run.llm_calls for run in runs]
    p50 = statistics.median(answered_totals) if answered_totals else None
    p90 = percentile(answered_totals, 90)
    mean_calls = statistics.fmean(calls) if calls else None
    return {
        "items": len(results),
        "outcomes": {
            outcome: sum(r.outcome == outcome for r in results)
            for outcome in ("answered", "abstained", "out_of_scope")
        },
        "errors": sum(r.error is not None for r in results),
        "paused_for_approval": sum(r.paused for r in results),
        "correct_outcomes": sum(r.correct for r in results),
        "unanswerable_abstained": sum(
            r.outcome == "abstained" for r in results if not r.item.answerable
        ),
        "unanswerable": sum(not r.item.answerable for r in results),
        "answered_with_citations": sum(r.citations > 0 for r in answered),
        "first_event_seconds_max": _round(max(firsts) if firsts else None),
        "first_event_seconds_p50": _round(statistics.median(firsts) if firsts else None),
        "total_seconds_p50": _round(statistics.median(totals) if totals else None),
        "total_seconds_p90": _round(percentile(totals, 90)),
        "answered_seconds_p50": _round(p50),
        "answered_seconds_p90": _round(p90),
        "llm_calls_mean": _round(mean_calls),
        "llm_calls_max": max(calls) if calls else None,
        "tokens_mean": _round(statistics.fmean(run.tokens for run in runs) if runs else None, 0),
        "runs_read": len(runs),
        "nfr_01_first_event": bool(firsts) and max(firsts) <= NFR_01_FIRST_EVENT_SECONDS,
        "nfr_01_answer_latency": p50 is not None
        and p90 is not None
        and p50 <= NFR_01_P50_SECONDS
        and p90 <= NFR_01_P90_SECONDS,
        "nfr_13_llm_calls": mean_calls is not None and mean_calls <= NFR_13_MEAN_LLM_CALLS,
    }


def item_record(result: ItemMeasurement) -> dict[str, Any]:
    """One item's row in the experiment JSON."""
    run = result.run
    return {
        "id": result.item.id,
        "type": result.item.type,
        "corpus": result.item.corpus,
        "answerable": result.item.answerable,
        "run_id": None if result.run_id is None else str(result.run_id),
        "outcome": result.outcome,
        "correct": result.correct,
        "error": result.error,
        "paused_for_approval": result.paused,
        "stages": result.stages,
        "claims": result.claims,
        "citations": result.citations,
        "first_event_seconds": _round(result.first_event_seconds),
        "ask_seconds": _round(result.ask_seconds),
        "resume_seconds": _round(result.resume_seconds),
        "total_seconds": _round(result.total_seconds),
        "run_status": None if run is None else run.status,
        "llm_calls": None if run is None else run.llm_calls,
        "tokens": None if run is None else run.tokens,
        "run_latency_ms": None if run is None else run.latency_ms,
    }


def report(results: Sequence[ItemMeasurement], summary: dict[str, Any]) -> str:
    """Human-readable table and verdicts."""
    lines = [
        "| Item | Type | Outcome | Paused | First event (s) | Total (s) | LLM calls | Tokens |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for r in results:
        row = item_record(r)
        lines.append(
            f"| {r.item.id} | {r.item.type} | {r.outcome or r.error} | "
            f"{'yes' if r.paused else 'no'} | {row['first_event_seconds']} | "
            f"{row['total_seconds']} | {row['llm_calls']} | {row['tokens']} |"
        )

    def verdict(ok: bool) -> str:
        return "within" if ok else "OVER"

    lines += [
        "",
        f"Correct outcomes: {summary['correct_outcomes']}/{summary['items']} "
        f"(unanswerable abstained {summary['unanswerable_abstained']}/{summary['unanswerable']}; "
        f"paused for approval {summary['paused_for_approval']}; errors {summary['errors']})",
        f"NFR-01 first event: max {summary['first_event_seconds_max']} s "
        f"(≤ {NFR_01_FIRST_EVENT_SECONDS:.0f} s): {verdict(summary['nfr_01_first_event'])}",
        f"NFR-01 answered p50 / p90: {summary['answered_seconds_p50']} / "
        f"{summary['answered_seconds_p90']} s (≤ {NFR_01_P50_SECONDS:.0f} / "
        f"{NFR_01_P90_SECONDS:.0f} s): {verdict(summary['nfr_01_answer_latency'])}",
        f"NFR-13 LLM calls per question: mean {summary['llm_calls_mean']}, max "
        f"{summary['llm_calls_max']} (≤ {NFR_13_MEAN_LLM_CALLS:.0f} on average): "
        f"{verdict(summary['nfr_13_llm_calls'])}",
    ]
    return "\n".join(lines)


def token_user(token: str) -> UUID:
    """The `sub` claim of an access token, read without verifying it.

    Only used to filter `agent_runs` to the measuring user's own runs.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return UUID(claims["sub"])
    except (IndexError, KeyError, ValueError) as error:
        raise MeasurementError("the access token has no readable user id (sub)") from error


def database_run_reader(settings: Settings, user_id: UUID) -> RunReader:
    """Read run stats from `agent_runs` in the database `DATABASE_URL` points at.

    A missing run means the database is not the one the measured backend uses.
    """

    async def read(run_ids: Sequence[UUID]) -> dict[UUID, RunStats]:
        engine = create_engine_from_settings(settings)
        if engine is None:
            raise MeasurementError("DATABASE_URL is not set; it must be the backend's database")
        try:
            async with create_sessionmaker(engine)() as session:
                repository = ConversationRepository(session)
                stats = {}
                for run_id in run_ids:
                    run = await repository.get_run(user_id, run_id)
                    if run is None:
                        raise MeasurementError(
                            f"run {run_id} is not in this database; set DATABASE_URL to the "
                            "measured backend's database"
                        )
                    stats[run_id] = RunStats(run.status, run.llm_calls, run.tokens, run.latency_ms)
                return stats
        finally:
            await engine.dispose()

    return read


def select_items(ids: Sequence[str]) -> list[BenchmarkItem]:
    """The benchmark items with these ids, in the given order."""
    by_id = {item.id: item for item in load_items()}
    missing = [item_id for item_id in ids if item_id not in by_id]
    if missing:
        raise MeasurementError(f"unknown benchmark items: {missing}")
    return [by_id[item_id] for item_id in ids]


def server_defaults() -> Settings:
    """Config defaults at this commit plus the providers the Dockerfile sets.

    The server's real settings cannot be read over the API, so the record says so.
    """
    return Settings.model_construct(
        embedding_provider="sentence_transformers",
        reranker_provider="cross_encoder",
        nli_provider="cross_encoder",
        parser_provider="pymupdf4llm",
        llm_fast_provider="groq",
        llm_strong_provider="gemini",
    )


async def run(
    args: argparse.Namespace,
    token: str,
    *,
    read_runs: RunReader | None = None,
    corpora: dict[str, list[Path]] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Measure, print, write the experiment JSON; return the exit code."""
    settings = get_settings()
    try:
        items = select_items(args.ids)
        corpora = load_corpora() if corpora is None else corpora
        missing = [p for i in items for p in corpora[i.corpus] if not p.exists()]
        if missing:
            raise MeasurementError(f"missing PDFs (eval/data/corpora_v1.json): {missing}")
        reader = read_runs or database_run_reader(settings, token_user(token))
        async with httpx.AsyncClient(
            base_url=args.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(args.request_timeout_seconds),
            transport=transport,
        ) as client:
            results = await measure(
                client,
                items,
                corpora,
                reader,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
                sleep=sleep,
            )
    except MeasurementError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    summary = summarize(results)
    print(report(results, summary))
    defaults = server_defaults()
    path = write_experiment(
        "measure_qa",
        settings=defaults,
        models={
            "llm_fast": f"{defaults.llm_fast_provider}/{defaults.llm_fast_model}",
            "llm_strong": f"{defaults.llm_strong_provider}/{defaults.llm_strong_model}",
            "nli": defaults.nli_model,
            "source": "config defaults at this commit and Dockerfile providers, not read from "
            "the server",
        },
        dataset="benchmark_v1 " + ",".join(args.ids),
        parameters={
            "base_url": args.base_url,
            "resume_decision": "corpus_only",
            "poll_seconds": args.poll_seconds,
            "timeout_seconds": args.timeout_seconds,
        },
        hardware_extra={"measured_from": "client", "server": args.server_hardware},
        results=[item_record(r) for r in results],
        summary={
            **summary,
            "nfr_01_first_event_limit_seconds": NFR_01_FIRST_EVENT_SECONDS,
            "nfr_01_p50_limit_seconds": NFR_01_P50_SECONDS,
            "nfr_01_p90_limit_seconds": NFR_01_P90_SECONDS,
            "nfr_13_mean_llm_calls_limit": NFR_13_MEAN_LLM_CALLS,
        },
        secrets=[token, *secret_values(settings)],
    )
    print(f"Wrote {path}")
    ok = summary["errors"] == 0 and summary["runs_read"] == len(results)
    return 0 if ok else 1


def main() -> None:
    """Parse arguments and run the measurement."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="e.g. https://<space>.hf.space")
    parser.add_argument("--token", help="Supabase access token (default: $MEASURE_TOKEN)")
    parser.add_argument("--server-hardware", help='e.g. "HF Spaces cpu-basic (2 vCPU)"')
    parser.add_argument(
        "--ids", nargs="+", default=list(SAMPLE_IDS), help="benchmark item ids (default: sample)"
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0, help="per corpus")
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    token = args.token or os.environ.get("MEASURE_TOKEN")
    if not token:
        parser.error("pass --token or set MEASURE_TOKEN")
    sys.exit(asyncio.run(run(args, token)))


if __name__ == "__main__":
    main()
