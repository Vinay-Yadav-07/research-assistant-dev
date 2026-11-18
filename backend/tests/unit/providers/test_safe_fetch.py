"""The PDF downloader for paper import refuses internal destinations (SSRF, D-077).

Network-free: a fake resolver and httpcore's mock backend stand in for DNS and sockets.
"""

from collections.abc import Iterable

import anyio
import httpcore
import pytest

from app.core.errors import PdfUnavailableError
from app.providers.live.safe_fetch import (
    PinnedBackend,
    SafePdfFetcher,
    UnsafeDestinationError,
    check_url,
    is_public_address,
)

PUBLIC = "93.184.215.14"
PDF_BODY = b"%PDF-1.7\n" + b"x" * 100


def http(status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> list[bytes]:
    lines = [f"HTTP/1.1 {status} X", f"Content-Length: {len(body)}"]
    lines += [f"{key}: {value}" for key, value in (headers or {}).items()]
    return [("\r\n".join(lines) + "\r\n\r\n").encode(), body]


class RecordingBackend(httpcore.AsyncMockBackend):
    """Answers every connection with the same canned response; records where it connected."""

    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.connected: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected.append(host)
        return await super().connect_tcp(host, port, timeout, local_address, socket_options)


def resolver(table: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        if host not in table:
            raise OSError("unknown host")
        return table[host]

    return resolve


def fetcher(
    buffer: list[bytes], table: dict[str, list[str]], *, max_bytes: int = 10_000
) -> tuple[SafePdfFetcher, RecordingBackend]:
    inner = RecordingBackend(buffer)
    backend = PinnedBackend(resolve=resolver(table), inner=inner)
    return (
        SafePdfFetcher(
            max_bytes=max_bytes,
            max_redirects=2,
            timeout_seconds=5,
            user_agent="test",
            retry_delay_seconds=0,
            backend=backend,
        ),
        inner,
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1%eth0",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
        "not-an-ip",
    ],
)
def test_internal_addresses_are_not_public(address: str) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize("address", [PUBLIC, "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
def test_global_addresses_are_public(address: str) -> None:
    assert is_public_address(address)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/a.pdf",
        "gopher://example.org/",
        "https://user:pw@example.org/a.pdf",
        "https://example.org:8080/a.pdf",
        "http://example.org:443/a.pdf",
        "https:///a.pdf",
        "not a url",
    ],
)
def test_only_plain_http_urls_on_default_ports_are_allowed(url: str) -> None:
    with pytest.raises(UnsafeDestinationError):
        check_url(url)


async def test_downloads_a_pdf_from_the_validated_address() -> None:
    fetch, inner = fetcher(http(200, PDF_BODY), {"repo.example.org": [PUBLIC]})

    assert await fetch.fetch("https://repo.example.org/a.pdf") == PDF_BODY
    assert inner.connected == [PUBLIC]  # the socket goes to the checked IP, not a new lookup


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], [PUBLIC, "10.0.0.5"], ["::ffff:10.0.0.5"], []]
)
async def test_a_name_with_any_internal_address_is_refused(addresses: list[str]) -> None:
    fetch, inner = fetcher(http(200, PDF_BODY), {"evil.example.org": addresses})

    with pytest.raises(UnsafeDestinationError):
        await fetch.fetch("https://evil.example.org/a.pdf")
    assert inner.connected == []


async def test_ip_literal_urls_are_checked_too() -> None:
    fetch, inner = fetcher(http(200, PDF_BODY), {"169.254.169.254": ["169.254.169.254"]})

    with pytest.raises(UnsafeDestinationError):
        await fetch.fetch("http://169.254.169.254/latest/meta-data")
    assert inner.connected == []


async def test_a_redirect_to_an_internal_host_is_refused_at_connect() -> None:
    redirect = http(302, headers={"Location": "http://internal.example.org/secret.pdf"})
    table = {"repo.example.org": [PUBLIC], "internal.example.org": ["10.0.0.7"]}
    fetch, inner = fetcher(redirect, table)

    with pytest.raises(UnsafeDestinationError):
        await fetch.fetch("https://repo.example.org/a.pdf")
    assert inner.connected == [PUBLIC]


async def test_a_redirect_to_another_scheme_is_refused() -> None:
    redirect = http(301, headers={"Location": "file:///etc/passwd"})
    fetch, _ = fetcher(redirect, {"repo.example.org": [PUBLIC]})

    with pytest.raises(UnsafeDestinationError):
        await fetch.fetch("https://repo.example.org/a.pdf")


async def test_redirect_chains_are_bounded() -> None:
    redirect = http(302, headers={"Location": "/again.pdf"})
    fetch, inner = fetcher(redirect, {"repo.example.org": [PUBLIC]})

    with pytest.raises(PdfUnavailableError, match="Too many redirects"):
        await fetch.fetch("https://repo.example.org/a.pdf")
    assert len(inner.connected) >= 1


async def test_an_oversized_body_is_cut_off() -> None:
    big = b"%PDF-1.7\n" + b"x" * 5000
    fetch, _ = fetcher(http(200, big), {"repo.example.org": [PUBLIC]}, max_bytes=1000)

    with pytest.raises(PdfUnavailableError, match="larger than the upload limit"):
        await fetch.fetch("https://repo.example.org/a.pdf")


async def test_an_oversized_stream_without_length_is_cut_off() -> None:
    chunked = [
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
        b"%x\r\n" % 2000 + b"%PDF-" + b"x" * 1995 + b"\r\n0\r\n\r\n",
    ]
    fetch, _ = fetcher(chunked, {"repo.example.org": [PUBLIC]}, max_bytes=1000)

    with pytest.raises(PdfUnavailableError, match="larger than the upload limit"):
        await fetch.fetch("https://repo.example.org/a.pdf")


async def test_a_landing_page_is_not_a_pdf() -> None:
    fetch, _ = fetcher(http(200, b"<html>Paper page</html>"), {"repo.example.org": [PUBLIC]})

    with pytest.raises(PdfUnavailableError, match="did not return a PDF"):
        await fetch.fetch("https://repo.example.org/a.pdf")


async def test_http_errors_are_unavailable() -> None:
    fetch, _ = fetcher(http(403), {"repo.example.org": [PUBLIC]})

    with pytest.raises(PdfUnavailableError, match="HTTP 403"):
        await fetch.fetch("https://repo.example.org/a.pdf")


async def test_unresolvable_hosts_are_unavailable() -> None:
    fetch, _ = fetcher(http(200, PDF_BODY), {})

    with pytest.raises(PdfUnavailableError, match="Could not resolve"):
        await fetch.fetch("https://nowhere.example.org/a.pdf")


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:80/a.pdf", "http://localhost/a.pdf", "http://[::1]/a.pdf"]
)
async def test_the_default_fetcher_is_wired_to_the_pinned_backend(url: str) -> None:
    """Real resolver, no mocks: loopback is refused before any socket opens."""
    fetch = SafePdfFetcher(max_bytes=1000, max_redirects=0, timeout_seconds=2, user_agent="t")

    with pytest.raises(UnsafeDestinationError):
        await fetch.fetch(url)


async def test_probe_reads_only_the_start_of_a_pdf() -> None:
    big = b"%PDF-1.7\n" + b"x" * 50_000
    fetch, _ = fetcher(http(200, big), {"repo.example.org": [PUBLIC]}, max_bytes=1000)

    assert await fetch.probe("https://repo.example.org/a.pdf") == "pdf"


async def test_probe_accepts_partial_content() -> None:
    fetch, _ = fetcher(http(206, PDF_BODY[:1024]), {"repo.example.org": [PUBLIC]})

    assert await fetch.probe("https://repo.example.org/a.pdf") == "pdf"


async def test_download_does_not_accept_partial_content() -> None:
    fetch, _ = fetcher(http(206, PDF_BODY), {"repo.example.org": [PUBLIC]})

    with pytest.raises(PdfUnavailableError, match="HTTP 206"):
        await fetch.fetch("https://repo.example.org/a.pdf")


@pytest.mark.parametrize(
    ("response", "addresses"),
    [
        (http(200, b"<html>Bot check</html>"), [PUBLIC]),
        (http(403), [PUBLIC]),
        (http(200, PDF_BODY), ["10.0.0.1"]),
    ],
)
async def test_probe_fails_for_blocked_or_unsafe_locations(
    response: list[bytes], addresses: list[str]
) -> None:
    fetch, _ = fetcher(response, {"repo.example.org": addresses})

    assert await fetch.probe("https://repo.example.org/a.pdf") == "failed"


# --- failure reasons and bounded retry ---


class SequenceBackend(httpcore.AsyncMockBackend):
    """Each new connection gets the next canned response (the last one repeats)."""

    def __init__(self, responses: list[list[bytes]], *, connect_delay: float = 0) -> None:
        super().__init__([])
        self._responses = responses
        self._delay = connect_delay
        self.connections = 0

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if self._delay:
            await anyio.sleep(self._delay)
        response = self._responses[min(self.connections, len(self._responses) - 1)]
        self.connections += 1
        return httpcore.AsyncMockStream(list(response))


def sequence_fetcher(
    responses: list[list[bytes]], *, deadline: float | None = None, connect_delay: float = 0
) -> tuple[SafePdfFetcher, SequenceBackend]:
    inner = SequenceBackend(responses, connect_delay=connect_delay)
    backend = PinnedBackend(resolve=resolver({"repo.example.org": [PUBLIC]}), inner=inner)
    fetch = SafePdfFetcher(
        max_bytes=10_000,
        max_redirects=2,
        timeout_seconds=5,
        user_agent="test",
        deadline_seconds=deadline,
        retry_delay_seconds=0,
        backend=backend,
    )
    return fetch, inner


URL = "https://repo.example.org/a.pdf"


def reason(error: pytest.ExceptionInfo[PdfUnavailableError]) -> object:
    return error.value.details.get("reason")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "access_denied"), (401, "access_denied"), (404, "not_found"), (400, "http_error")],
)
async def test_refusals_are_not_retried(status: int, expected: str) -> None:
    fetch, inner = sequence_fetcher([http(status), http(200, PDF_BODY)])

    with pytest.raises(PdfUnavailableError) as error:
        await fetch.fetch(URL)

    assert reason(error) == expected
    assert inner.connections == 1


async def test_a_non_pdf_is_not_retried() -> None:
    fetch, inner = sequence_fetcher([http(200, b"<html>Sign in</html>"), http(200, PDF_BODY)])

    with pytest.raises(PdfUnavailableError) as error:
        await fetch.fetch(URL)

    assert reason(error) == "not_pdf"
    assert inner.connections == 1


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_server_errors_are_retried_once_and_can_recover(status: int) -> None:
    fetch, inner = sequence_fetcher([http(status), http(200, PDF_BODY)])

    assert await fetch.fetch(URL) == PDF_BODY
    assert inner.connections == 2


async def test_persistent_server_errors_stop_after_one_retry() -> None:
    fetch, inner = sequence_fetcher([http(503)])

    with pytest.raises(PdfUnavailableError) as error:
        await fetch.fetch(URL)

    assert reason(error) == "server_error"
    assert inner.connections == 2


async def test_a_cut_off_body_is_incomplete_and_retried() -> None:
    cut = [b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n", PDF_BODY]
    fetch, inner = sequence_fetcher([cut, http(200, PDF_BODY)])

    assert await fetch.fetch(URL) == PDF_BODY
    assert inner.connections == 2


async def test_a_download_past_its_deadline_times_out_and_is_retried_once() -> None:
    fetch, inner = sequence_fetcher([http(200, PDF_BODY)], deadline=0.05, connect_delay=1)

    with pytest.raises(PdfUnavailableError) as error:
        await fetch.fetch(URL)

    assert reason(error) == "timeout"
    assert inner.connections == 0  # both attempts were cut off while connecting


async def test_network_failures_are_retried() -> None:
    calls = 0

    async def flaky(host: str, port: int) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary failure in name resolution")
        return [PUBLIC]

    inner = SequenceBackend([http(200, PDF_BODY)])
    fetch = SafePdfFetcher(
        max_bytes=10_000,
        max_redirects=0,
        timeout_seconds=5,
        user_agent="test",
        retry_delay_seconds=0,
        backend=PinnedBackend(resolve=flaky, inner=inner),
    )

    assert await fetch.fetch(URL) == PDF_BODY
    assert calls == 2


async def test_unsafe_destinations_are_never_retried() -> None:
    inner = SequenceBackend([http(200, PDF_BODY)])
    resolve_calls = 0

    async def internal(host: str, port: int) -> list[str]:
        nonlocal resolve_calls
        resolve_calls += 1
        return ["10.0.0.1"]

    fetch = SafePdfFetcher(
        max_bytes=10_000,
        max_redirects=0,
        timeout_seconds=5,
        user_agent="test",
        retry_delay_seconds=0,
        backend=PinnedBackend(resolve=internal, inner=inner),
    )

    with pytest.raises(UnsafeDestinationError) as error:
        await fetch.fetch(URL)

    assert reason(error) == "unsafe"
    assert resolve_calls == 1 and inner.connections == 0


@pytest.mark.parametrize(
    ("response", "expected"),
    [(http(503), "unknown"), (http(403), "failed"), (http(200, PDF_BODY), "pdf")],
)
async def test_probe_tells_inconclusive_from_failed(response: list[bytes], expected: str) -> None:
    fetch, inner = sequence_fetcher([response])

    assert await fetch.probe(URL) == expected
    assert inner.connections == 1  # probes are never retried
