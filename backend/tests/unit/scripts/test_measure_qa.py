import argparse
import base64
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.core.config import get_settings
from scripts import experiment_log
from scripts.measure_qa import (
    SAMPLE_IDS,
    MeasurementError,
    RunStats,
    measure,
    run,
    select_items,
    stream_events,
    summarize,
    token_user,
)

USER = "33333333-3333-3333-3333-333333333333"
SECRET_KEY = "sb_secret_0123456789abcdef"
DATABASE_URL = "postgresql+psycopg://postgres.abc:db-password-123@pooler.example.com:5432/postgres"
ANSWERABLE = "test-001"
UNANSWERABLE = "test-046"


def make_token(claims: dict[str, Any]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJFUzI1NiJ9.{payload}.signature"


TOKEN = make_token({"sub": USER, "role": "authenticated"})


def run_id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def sse(*events: dict[str, Any]) -> httpx.Response:
    body = ": ping\n\n" + "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def answered(rid: str) -> list[dict[str, Any]]:
    return [
        {"type": "status", "stage": "analyzing"},
        {"type": "status", "stage": "verifying"},
        {"type": "claims", "message_id": "m", "claims": [{}, {}]},
        {"type": "citations", "message_id": "m", "citations": [{}, {}, {}]},
        {"type": "done", "run_id": rid, "outcome": "answered", "message": {}},
    ]


class FakeApi:
    """Workspaces, uploads, documents, conversations, and SSE runs.

    A question containing "lysozyme" (test-046) pauses for approval; others are answered.
    """

    def __init__(self, *, ready_after: int = 1, fail_document: bool = False) -> None:
        self.ready_after = ready_after
        self.fail_document = fail_document
        self.calls: list[str] = []
        self.bodies: dict[str, Any] = {}
        self.polls: dict[str, int] = {}
        self.workspaces = 0
        self.documents = 0
        self.runs = 0
        self.authorization: set[str | None] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append(f"{method} {path}")
        self.authorization.add(request.headers.get("authorization"))
        if method == "POST" and path == "/api/v1/workspaces":
            self.workspaces += 1
            return httpx.Response(201, json={"id": f"ws-{self.workspaces}"})
        if method == "POST" and path.endswith("/documents"):
            self.documents += 1
            self.bodies[path] = request.content
            body = {"document": {"id": f"doc-{self.documents}", "status": "uploaded"}}
            return httpx.Response(202, json={**body, "duplicate": False, "linked": True})
        if method == "GET" and path.startswith("/api/v1/documents/"):
            document_id = path.rsplit("/", 1)[1]
            self.polls[document_id] = self.polls.get(document_id, 0) + 1
            if self.fail_document:
                return httpx.Response(200, json={"status": "failed", "error": "No text."})
            done = self.polls[document_id] > self.ready_after
            return httpx.Response(
                200, json={"status": "ready" if done else "parsing", "error": None}
            )
        if method == "POST" and path.endswith("/conversations"):
            return httpx.Response(201, json={"id": f"conv-{len(self.calls)}"})
        if method == "POST" and path.endswith("/messages"):
            self.runs += 1
            rid = run_id(self.runs)
            if "lysozyme" in json.loads(request.content)["content"]:
                return sse(
                    {"type": "status", "stage": "checking_sufficiency"},
                    {"type": "approval_required", "run_id": rid, "request": {}},
                )
            return sse(*answered(rid))
        if method == "POST" and path.startswith("/api/v1/runs/"):
            self.bodies[path] = json.loads(request.content)
            rid = path.split("/")[4]
            return sse({"type": "done", "run_id": rid, "outcome": "abstained", "message": {}})
        if method == "DELETE" and path.startswith("/api/v1/workspaces/"):
            return httpx.Response(204)
        return httpx.Response(404, json={"error": {"code": "not_found"}})


class FakeRuns:
    """Run stats per run id; records each read in the API call log."""

    def __init__(self, api: FakeApi, *, calls: int = 4) -> None:
        self.api = api
        self.llm_calls = calls

    async def __call__(self, run_ids: Sequence[UUID]) -> dict[UUID, RunStats]:
        self.api.calls.append("READ runs")
        return {rid: RunStats("completed", self.llm_calls, 9000, 12000) for rid in run_ids}


def ticking_clock(step: float = 1.0) -> Callable[[], float]:
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


async def no_sleep(seconds: float) -> None:
    return None


def corpora(tmp_path: Path) -> dict[str, list[Path]]:
    result = {}
    for corpus in ("tissue", "scaffolds"):
        papers = [tmp_path / f"{corpus}-{n}.pdf" for n in (1, 2)]
        for paper in papers:
            paper.write_bytes(b"%PDF-1.7")
        result[corpus] = papers
    return result


async def run_measure(api: FakeApi, ids: list[str], tmp_path: Path, **kwargs: Any) -> Any:
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        return await measure(
            client,
            select_items(ids),
            corpora(tmp_path),
            kwargs.pop("read_runs", FakeRuns(api)),
            poll_seconds=0.0,
            timeout_seconds=kwargs.pop("timeout_seconds", 60.0),
            clock=ticking_clock(),
            sleep=no_sleep,
        )


def test_sample_is_twelve_stratified_test_items() -> None:
    items = select_items(SAMPLE_IDS)

    assert len(items) == 12
    assert all(item.split == "test" for item in items)
    types = [item.type for item in items]
    assert {t: types.count(t) for t in set(types)} == {
        "single": 7,
        "multi": 2,
        "comparison": 1,
        "unanswerable": 2,
    }
    assert {item.corpus for item in items} == {"tissue", "scaffolds"}


def test_unknown_item_is_an_error() -> None:
    with pytest.raises(MeasurementError, match="unknown benchmark items"):
        select_items(["test-999"])


async def test_stream_times_first_data_event_and_skips_keepalives() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return sse({"type": "status", "stage": "analyzing"}, *answered(run_id(1)))

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        stream = await stream_events(client, "/x", {}, clock=ticking_clock())

    assert [e["type"] for e in stream.events] == [
        "status",
        "status",
        "status",
        "claims",
        "citations",
        "done",
    ]
    assert stream.first_event_seconds == 1.0
    assert stream.seconds > stream.first_event_seconds


async def test_stream_api_error_is_reported() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(refuse)
    ) as client:
        with pytest.raises(MeasurementError, match="HTTP 404"):
            await stream_events(client, "/x", {})


async def test_answers_resumes_paused_runs_reads_stats_then_deletes(tmp_path: Path) -> None:
    api = FakeApi(ready_after=2)

    results = await run_measure(api, [ANSWERABLE, UNANSWERABLE, "test-020"], tmp_path)

    first, paused, other = results
    assert (first.outcome, first.claims, first.citations, first.paused) == (
        "answered",
        2,
        3,
        False,
    )
    assert first.stages == ["analyzing", "verifying"]
    assert first.correct and paused.correct and other.correct
    assert paused.outcome == "abstained" and paused.paused
    assert paused.total_seconds == paused.ask_seconds + paused.resume_seconds
    assert api.bodies[f"/api/v1/runs/{run_id(2)}/resume"] == {"decision": "corpus_only"}
    assert all(r.run == RunStats("completed", 4, 9000, 12000) for r in results)
    # One workspace per corpus, each paper uploaded with override and polled until ready.
    assert api.workspaces == 2 and api.documents == 4
    assert all(
        b'name="override"' in body for body in api.bodies.values() if isinstance(body, bytes)
    )
    assert all(polls == 3 for polls in api.polls.values())
    # Runs are read before the workspaces (and with them the runs) are deleted.
    read = api.calls.index("READ runs")
    deletes = [i for i, call in enumerate(api.calls) if call.startswith("DELETE")]
    assert len(deletes) == 2 and min(deletes) > read


async def test_failed_ingestion_is_an_error_and_workspaces_are_deleted(tmp_path: Path) -> None:
    api = FakeApi(fail_document=True)

    with pytest.raises(MeasurementError, match="failed to ingest: No text."):
        await run_measure(api, [ANSWERABLE], tmp_path)

    assert api.calls[-1] == "DELETE /api/v1/workspaces/ws-1"


async def test_ingestion_timeout_is_an_error_and_workspaces_are_deleted(tmp_path: Path) -> None:
    api = FakeApi(ready_after=1000)

    with pytest.raises(MeasurementError, match="not ready after"):
        await run_measure(api, [ANSWERABLE], tmp_path, timeout_seconds=5)

    assert api.calls[-1] == "DELETE /api/v1/workspaces/ws-1"


async def test_run_reader_error_still_deletes_every_workspace(tmp_path: Path) -> None:
    api = FakeApi()

    async def missing(run_ids: Sequence[UUID]) -> dict[UUID, RunStats]:
        raise MeasurementError("run is not in this database")

    with pytest.raises(MeasurementError, match="not in this database"):
        await run_measure(api, [ANSWERABLE, "test-020"], tmp_path, read_runs=missing)

    assert api.calls[-2:] == [
        "DELETE /api/v1/workspaces/ws-1",
        "DELETE /api/v1/workspaces/ws-2",
    ]


async def test_summary_reports_latency_cost_and_verdicts(tmp_path: Path) -> None:
    api = FakeApi()
    results = await run_measure(
        api, [ANSWERABLE, UNANSWERABLE], tmp_path, read_runs=FakeRuns(api, calls=12)
    )

    summary = summarize(results)

    assert summary["items"] == 2
    assert summary["outcomes"] == {"answered": 1, "abstained": 1, "out_of_scope": 0}
    assert summary["correct_outcomes"] == 2
    assert summary["unanswerable_abstained"] == summary["unanswerable"] == 1
    assert summary["paused_for_approval"] == 1
    assert summary["answered_with_citations"] == 1
    assert summary["llm_calls_mean"] == 12 and summary["llm_calls_max"] == 12
    assert summary["runs_read"] == 2
    # The ticking clock makes every step 1 s: first event within 2 s, but 12 calls > 10.
    assert summary["nfr_01_first_event"] is True
    assert summary["nfr_13_llm_calls"] is False
    assert summary["answered_seconds_p50"] == results[0].total_seconds


def test_summary_of_nothing_fails_every_verdict() -> None:
    summary = summarize([])

    assert summary["llm_calls_mean"] is None
    assert not summary["nfr_01_first_event"]
    assert not summary["nfr_01_answer_latency"]
    assert not summary["nfr_13_llm_calls"]


def test_token_user_reads_sub_without_verifying() -> None:
    assert token_user(TOKEN) == UUID(USER)


@pytest.mark.parametrize("token", ["not-a-jwt", make_token({"role": "anon"})])
def test_token_without_user_is_an_error(token: str) -> None:
    with pytest.raises(MeasurementError, match="no readable user id"):
        token_user(token)


async def test_run_writes_json_without_token_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    get_settings.cache_clear()
    out = tmp_path / "experiments"
    monkeypatch.setattr(experiment_log, "EXPERIMENTS_DIR", out)
    api = FakeApi()
    args = argparse.Namespace(
        base_url="http://test",
        server_hardware="cpu-basic (2 vCPU)",
        ids=[ANSWERABLE, UNANSWERABLE],
        poll_seconds=0.0,
        timeout_seconds=60.0,
        request_timeout_seconds=10.0,
    )

    code = await run(
        args,
        TOKEN,
        read_runs=FakeRuns(api),
        corpora=corpora(tmp_path),
        transport=httpx.MockTransport(api),
        sleep=no_sleep,
    )

    assert code == 0
    assert api.authorization == {f"Bearer {TOKEN}"}
    [written] = list(out.glob("*_measure_qa_*.json"))
    text = written.read_text(encoding="utf-8")
    for value in (TOKEN, DATABASE_URL, "db-password-123", SECRET_KEY):
        assert value not in text
    record = json.loads(text)
    assert record["dataset"] == f"benchmark_v1 {ANSWERABLE},{UNANSWERABLE}"
    assert record["models"]["llm_fast"].startswith("groq/")
    assert record["models"]["llm_strong"].startswith("gemini/")
    assert [r["outcome"] for r in record["results"]] == ["answered", "abstained"]
    assert record["results"][1]["paused_for_approval"] is True
    assert record["summary"]["llm_calls_mean"] == 4
    assert record["summary"]["nfr_13_llm_calls"] is True


async def test_run_without_the_pdfs_fails_before_calling_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeApi()
    args = argparse.Namespace(
        base_url="http://test",
        server_hardware=None,
        ids=[ANSWERABLE],
        poll_seconds=0.0,
        timeout_seconds=1.0,
        request_timeout_seconds=1.0,
    )

    code = await run(
        args,
        TOKEN,
        read_runs=FakeRuns(api),
        corpora={"tissue": [tmp_path / "missing.pdf"]},
        transport=httpx.MockTransport(api),
    )

    assert code == 1
    assert api.calls == []
