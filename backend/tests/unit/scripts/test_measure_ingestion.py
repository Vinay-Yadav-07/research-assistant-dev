import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from scripts import experiment_log
from scripts.measure_ingestion import MeasurementError, measure, run

WORKSPACE = "11111111-1111-1111-1111-111111111111"
DOCUMENT = "22222222-2222-2222-2222-222222222222"
TOKEN = "eyJhbGciOiJFUzI1NiJ9.measure-token.signature"
DATABASE_URL = "postgresql+psycopg://postgres.abc:db-password-123@pooler.example.com:5432/postgres"
SECRET_KEY = "sb_secret_0123456789abcdef"


def document(status: str, *, error: str | None = None) -> dict[str, Any]:
    return {"id": DOCUMENT, "status": status, "page_count": 20, "error": error}


class FakeApi:
    """Answers the four calls `measure` makes; document statuses come from a list."""

    def __init__(self, statuses: list[str], *, duplicate: bool = False) -> None:
        self.statuses = statuses
        self.duplicate = duplicate
        self.calls: list[str] = []
        self.authorization: set[str | None] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        self.authorization.add(request.headers.get("authorization"))
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/workspaces":
            return httpx.Response(201, json={"id": WORKSPACE})
        if request.method == "POST" and path.endswith("/documents"):
            body = {"document": document("uploaded"), "duplicate": self.duplicate, "linked": True}
            return httpx.Response(200 if self.duplicate else 202, json=body)
        if request.method == "GET" and path == f"/api/v1/documents/{DOCUMENT}":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            error = "No text." if status == "failed" else None
            return httpx.Response(200, json=document(status, error=error))
        if request.method == "DELETE" and path == f"/api/v1/workspaces/{WORKSPACE}":
            return httpx.Response(204)
        return httpx.Response(404, json={"error": {"code": "not_found"}})


def ticking_clock(step: float = 1.0) -> Callable[[], float]:
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


def read_single_experiment(directory: Path) -> str:
    [written] = list(directory.glob("*_measure_ingestion_*.json"))
    return written.read_text(encoding="utf-8")


async def no_sleep(seconds: float) -> None:
    return None


async def run_measure(api: FakeApi, timeout_seconds: float = 600.0) -> Any:
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(api)
    ) as client:
        return await measure(
            client,
            "paper.pdf",
            b"%PDF-1.7",
            poll_seconds=0.5,
            timeout_seconds=timeout_seconds,
            clock=ticking_clock(),
            sleep=no_sleep,
        )


async def test_records_first_time_each_status_is_seen_and_deletes_the_workspace() -> None:
    api = FakeApi(["parsing", "parsing", "embedding", "ready"])

    result = await run_measure(api)

    assert result.final_status == "ready"
    assert list(result.stages) == ["uploaded", "parsing", "embedding", "ready"]
    stage_times = list(result.stages.values())
    assert stage_times == sorted(stage_times)
    assert result.total_seconds == result.stages["ready"]
    assert result.polls == 4
    assert result.page_count == 20
    assert api.calls[0] == "POST /api/v1/workspaces"
    assert api.calls[-1] == f"DELETE /api/v1/workspaces/{WORKSPACE}"


async def test_failed_ingestion_is_reported_with_its_reason() -> None:
    result = await run_measure(FakeApi(["parsing", "failed"]))

    assert result.final_status == "failed"
    assert result.error == "No text."


async def test_duplicate_upload_is_an_error_and_the_workspace_is_deleted() -> None:
    api = FakeApi(["ready"], duplicate=True)

    with pytest.raises(MeasurementError, match="already has the PDF"):
        await run_measure(api)

    assert api.calls[-1] == f"DELETE /api/v1/workspaces/{WORKSPACE}"


async def test_timeout_is_an_error_and_the_workspace_is_deleted() -> None:
    api = FakeApi(["parsing"])

    with pytest.raises(MeasurementError, match="not ready after"):
        await run_measure(api, timeout_seconds=5)

    assert api.calls[-1] == f"DELETE /api/v1/workspaces/{WORKSPACE}"


async def test_api_error_is_reported() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(refuse)
    ) as client:
        with pytest.raises(MeasurementError, match="create workspace failed: HTTP 401"):
            await measure(client, "paper.pdf", b"%PDF", poll_seconds=0, timeout_seconds=1)


async def test_run_writes_json_without_token_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    get_settings.cache_clear()
    monkeypatch.setattr(experiment_log, "EXPERIMENTS_DIR", tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    api = FakeApi(["parsing", "embedding", "ready"])
    args = argparse.Namespace(
        base_url="http://test",
        pdf=pdf,
        server_hardware="cpu-basic (2 vCPU)",
        poll_seconds=0.0,
        timeout_seconds=60.0,
    )

    assert await run(args, TOKEN, transport=httpx.MockTransport(api)) == 0

    assert api.authorization == {f"Bearer {TOKEN}"}
    text = read_single_experiment(tmp_path)
    for value in (TOKEN, "measure-token", DATABASE_URL, "db-password-123", SECRET_KEY):
        assert value not in text
    record = json.loads(text)
    assert record["dataset"] == "paper.pdf"
    assert record["hardware"]["server"] == "cpu-basic (2 vCPU)"
    assert record["settings"]["embedding_provider"] == "sentence_transformers"
    assert record["results"][0]["final_status"] == "ready"
    assert set(record["results"][0]["stages_first_seen_seconds"]) == {
        "uploaded",
        "parsing",
        "embedding",
        "ready",
    }
    assert record["summary"]["within_nfr_02"] is True
