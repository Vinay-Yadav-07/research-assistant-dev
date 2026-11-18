"""Supabase Storage REST client against a mock transport."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.repositories.storage import SupabaseStorage, create_storage_from_settings

URL = "https://project.supabase.co"


class Recorder:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json={})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def storage(handler: Recorder) -> SupabaseStorage:
    return SupabaseStorage(
        supabase_url=URL,
        secret_key="sb_secret_test",
        bucket="documents",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


async def test_upload_sends_the_pdf_with_the_secret_key() -> None:
    recorder = Recorder()

    await storage(recorder).upload_pdf("user/doc.pdf", b"%PDF-1.7")

    [request] = recorder.requests
    assert request.method == "POST"
    assert str(request.url) == f"{URL}/storage/v1/object/documents/user/doc.pdf"
    assert request.headers["apikey"] == "sb_secret_test"
    assert request.headers["content-type"] == "application/pdf"
    assert request.headers["x-upsert"] == "true"
    assert request.content == b"%PDF-1.7"


async def test_signed_url_is_absolute_and_short_lived() -> None:
    recorder = Recorder(
        httpx.Response(200, json={"signedURL": "/object/sign/documents/u/d.pdf?token=abc"})
    )

    url, expires_at = await storage(recorder).signed_url("u/d.pdf", expires_in=300)

    assert url == f"{URL}/storage/v1/object/sign/documents/u/d.pdf?token=abc"
    assert json.loads(recorder.requests[0].content) == {"expiresIn": 300}
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(seconds=290) < remaining <= timedelta(seconds=300)


async def test_signed_url_without_url_in_response_is_an_error() -> None:
    with pytest.raises(ExternalServiceError):
        await storage(Recorder()).signed_url("u/d.pdf", expires_in=60)


async def test_delete_sends_all_paths_in_one_request() -> None:
    recorder = Recorder(httpx.Response(200, json=[]))

    await storage(recorder).delete(["a/1.pdf", "a/2.pdf"])

    [request] = recorder.requests
    assert request.method == "DELETE"
    assert str(request.url) == f"{URL}/storage/v1/object/documents"
    assert json.loads(request.content) == {"prefixes": ["a/1.pdf", "a/2.pdf"]}


async def test_delete_nothing_makes_no_request() -> None:
    recorder = Recorder()

    await storage(recorder).delete([])

    assert recorder.requests == []


async def test_error_status_is_an_external_service_error() -> None:
    recorder = Recorder(httpx.Response(400, json={"statusCode": "404", "error": "not_found"}))

    with pytest.raises(ExternalServiceError) as raised:
        await storage(recorder).signed_url("missing.pdf", expires_in=60)

    assert raised.value.details == {"service": "storage", "status": 400}


async def test_network_failure_is_an_external_service_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = SupabaseStorage(
        supabase_url=URL,
        secret_key="k",
        bucket="documents",
        timeout_seconds=5,
        transport=httpx.MockTransport(fail),
    )

    with pytest.raises(ExternalServiceError, match="unreachable"):
        await client.upload_pdf("p.pdf", b"%PDF-")


def test_storage_needs_url_and_secret_key(clean_env: pytest.MonkeyPatch) -> None:
    assert create_storage_from_settings(Settings(_env_file=None)) is None
    assert create_storage_from_settings(Settings(_env_file=None, supabase_url=URL)) is None
    configured = Settings(_env_file=None, supabase_url=URL, supabase_secret_key="sb_secret_x")
    assert isinstance(create_storage_from_settings(configured), SupabaseStorage)
