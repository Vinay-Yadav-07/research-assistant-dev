"""Measure ingestion time (NFR-02: a 20-page paper ready in 90 s) over the public API.

Run from `backend/` against a running backend, e.g. the Space:
    MEASURE_TOKEN=<access token> uv run python -m scripts.measure_ingestion \\
        --base-url https://<space>.hf.space \\
        --pdf scripts/data/embedding_comparison/2303.11051.pdf \\
        --server-hardware "HF Spaces cpu-basic (2 vCPU)"

Creates a workspace, uploads the PDF, polls the document until `ready` or `failed`, prints the
total time and the time each status was first seen (stage timings, accurate to the poll
interval), and deletes the workspace afterwards, which also deletes the document (D-046). The
clock starts before the upload, so the total includes the upload. The user must not already have
this PDF (a duplicate is not ingested again). Writes the experiment JSON; the access token is
never written. `--token` also works, but the environment variable keeps it out of shell history.
"""

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from scripts.experiment_log import secret_values, write_experiment

API = "/api/v1"
FINAL_STATUSES = ("ready", "failed")
NFR_02_SECONDS = 90.0


class MeasurementError(RuntimeError):
    """The measurement could not be made (API error, duplicate upload, timeout)."""


@dataclass
class Measurement:
    """Outcome of one ingestion measurement; times are seconds since the upload started."""

    document_id: str
    upload_seconds: float
    final_status: str
    total_seconds: float
    page_count: int | None
    error: str | None
    # Status → first time it was seen while polling.
    stages: dict[str, float] = field(default_factory=dict)
    polls: int = 0


def check(response: httpx.Response, action: str) -> httpx.Response:
    """Raise `MeasurementError` with the API error body unless the response is 2xx."""
    if response.is_success:
        return response
    raise MeasurementError(f"{action} failed: HTTP {response.status_code} {response.text[:300]}")


async def measure(
    client: httpx.AsyncClient,
    pdf_name: str,
    data: bytes,
    *,
    poll_seconds: float,
    timeout_seconds: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Measurement:
    """Create a workspace, upload, poll to a final status, and always delete the workspace."""
    created = check(
        await client.post(f"{API}/workspaces", json={"name": f"NFR-02 measurement: {pdf_name}"}),
        "create workspace",
    )
    workspace_id = created.json()["id"]
    try:
        started = clock()
        upload = check(
            await client.post(
                f"{API}/workspaces/{workspace_id}/documents",
                files={"file": (pdf_name, data, "application/pdf")},
            ),
            "upload",
        ).json()
        upload_seconds = clock() - started
        if upload["duplicate"]:
            raise MeasurementError(
                "this user already has the PDF, so it is not ingested again; delete the existing "
                "copy or use another user"
            )
        document_id = upload["document"]["id"]
        result = Measurement(
            document_id=document_id,
            upload_seconds=upload_seconds,
            final_status=upload["document"]["status"],
            total_seconds=upload_seconds,
            page_count=None,
            error=None,
            stages={upload["document"]["status"]: upload_seconds},
        )
        while result.final_status not in FINAL_STATUSES:
            if clock() - started > timeout_seconds:
                raise MeasurementError(
                    f"not ready after {timeout_seconds:.0f} s (last status {result.final_status})"
                )
            await sleep(poll_seconds)
            document = check(
                await client.get(f"{API}/documents/{document_id}"), "get document"
            ).json()
            seen = clock() - started
            result.polls += 1
            result.final_status = document["status"]
            result.stages.setdefault(document["status"], seen)
            result.total_seconds = seen
            result.page_count = document["page_count"]
            result.error = document["error"]
        return result
    finally:
        check(await client.delete(f"{API}/workspaces/{workspace_id}"), "delete workspace")


def report(measurement: Measurement) -> str:
    """Human-readable summary."""
    lines = [
        f"status {measurement.final_status} after {measurement.total_seconds:.1f} s "
        f"({measurement.page_count} pages; upload {measurement.upload_seconds:.1f} s; "
        f"{measurement.polls} polls)"
    ]
    for status, at in measurement.stages.items():
        lines.append(f"  {status:>10} first seen at {at:6.1f} s")
    if measurement.error:
        lines.append(f"  error: {measurement.error}")
    if measurement.final_status == "ready":
        verdict = "within" if measurement.total_seconds <= NFR_02_SECONDS else "OVER"
        lines.append(f"NFR-02 ({NFR_02_SECONDS:.0f} s): {verdict}")
    return "\n".join(lines)


def server_defaults() -> Settings:
    """Config defaults at this commit plus the providers the Dockerfile sets.

    The server's real settings cannot be read over the API, so the record says so.
    """
    return Settings.model_construct(
        embedding_provider="sentence_transformers",
        reranker_provider="cross_encoder",
        nli_provider="cross_encoder",
        parser_provider="pymupdf4llm",
    )


async def run(
    args: argparse.Namespace, token: str, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    """Measure once, print, write the experiment JSON; return the exit code."""
    data = await asyncio.to_thread(args.pdf.read_bytes)
    async with httpx.AsyncClient(
        base_url=args.base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(120.0),
        transport=transport,
    ) as client:
        try:
            result = await measure(
                client,
                args.pdf.name,
                data,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
            )
        except MeasurementError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    print(report(result))
    stages = {status: round(at, 2) for status, at in result.stages.items()}
    path = write_experiment(
        "measure_ingestion",
        settings=server_defaults(),
        models={
            "embedding": server_defaults().embedding_model,
            "source": "config defaults at this commit and Dockerfile providers, not read from "
            "the server",
        },
        dataset=args.pdf.name,
        parameters={
            "base_url": args.base_url,
            "poll_seconds": args.poll_seconds,
            "timeout_seconds": args.timeout_seconds,
        },
        hardware_extra={"measured_from": "client", "server": args.server_hardware},
        results=[
            {
                "pdf": args.pdf.name,
                "bytes": len(data),
                "page_count": result.page_count,
                "final_status": result.final_status,
                "error": result.error,
                "upload_seconds": round(result.upload_seconds, 2),
                "stages_first_seen_seconds": stages,
                "polls": result.polls,
            }
        ],
        summary={
            "total_seconds": round(result.total_seconds, 2),
            "nfr_02_seconds": NFR_02_SECONDS,
            "within_nfr_02": result.final_status == "ready"
            and result.total_seconds <= NFR_02_SECONDS,
        },
        secrets=[token, *secret_values(get_settings())],
    )
    print(f"Wrote {path}")
    return 0 if result.final_status == "ready" else 1


def main() -> None:
    """Parse arguments and run one measurement."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="e.g. https://<space>.hf.space")
    parser.add_argument("--token", help="Supabase access token (default: $MEASURE_TOKEN)")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--server-hardware", help='e.g. "HF Spaces cpu-basic (2 vCPU)"')
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args()
    token = args.token or os.environ.get("MEASURE_TOKEN")
    if not token:
        parser.error("pass --token or set MEASURE_TOKEN")
    sys.exit(asyncio.run(run(args, token)))


if __name__ == "__main__":
    main()
