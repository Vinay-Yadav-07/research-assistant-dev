"""Download a PDF from an untrusted URL without letting it reach internal networks (D-077).

Paper import fetches URLs that come from third-party metadata (OpenAlex locations, arXiv), so
each one is treated as hostile. The check sits at the socket: `PinnedBackend` resolves the
host once, refuses the connection unless every resolved address is public, and then connects
to that same address. Redirect hops open new connections and pass through the same check, and
because there is no second lookup, DNS rebinding cannot swap the address after validation.
TLS still verifies the certificate against the host name (httpcore passes the origin host as
`server_hostname`). httpcore is used directly (public `network_backend` parameter) and never
reads proxy settings from the environment.
"""

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable

import anyio
import httpcore
import httpx

from app.core.errors import PdfUnavailableError
from app.providers.fetch import PdfFetcher, ProbeResult, is_transient

PDF_MAGIC = b"%PDF-"
PDF_MAGIC_WINDOW = 1024
ALLOWED_PORTS = {"http": 80, "https": 443}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
# NAT64 (RFC 6052) embeds an IPv4 address that must be checked itself.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

# (host, port) -> IP address strings.
Resolver = Callable[[str, int], Awaitable[list[str]]]


class UnsafeDestinationError(PdfUnavailableError):
    """The URL or the address it resolves to is not allowed (private, loopback, ...)."""

    code = "unsafe_destination"
    default_message = "The PDF location is not a public internet address."

    def __init__(self, message: str | None = None, *, details: dict[str, object] | None = None):
        super().__init__(message, details={"reason": "unsafe", **(details or {})})


def unavailable(message: str, reason: str) -> PdfUnavailableError:
    """A PDF location failure carrying its `FailureReason`."""
    return PdfUnavailableError(message, details={"reason": reason})


def _status_failure(status: int) -> PdfUnavailableError:
    if status in (401, 403, 451):
        reason = "access_denied"
    elif status in (404, 410):
        reason = "not_found"
    elif status == 429 or status >= 500:
        reason = "server_error"
    else:
        reason = "http_error"
    return unavailable(f"HTTP {status}.", reason)


async def resolve_host(host: str, port: int) -> list[str]:
    """All addresses the system resolver returns for the host."""
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_public_address(address: str) -> bool:
    """True only for globally routable unicast addresses, IPv4-in-IPv6 forms included."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


class PinnedBackend(httpcore.AsyncNetworkBackend):
    """Connects only to public addresses, and only to the address it validated."""

    def __init__(
        self,
        *,
        resolve: Resolver = resolve_host,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._resolve = resolve
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            with anyio.fail_after(timeout):
                addresses = await self._resolve(host, port)
        except (OSError, TimeoutError) as error:
            raise unavailable(f"Could not resolve {host}.", "network") from error
        # A name with any internal address is refused, so no fallback can reach it.
        if not addresses or not all(is_public_address(address) for address in addresses):
            raise UnsafeDestinationError(details={"host": host})
        return await self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (httpcore's interface)
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise UnsafeDestinationError("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def check_url(url: str) -> httpx.URL:
    """Parse the URL; only plain http(s) on the default ports, without credentials."""
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as error:
        raise UnsafeDestinationError("Invalid URL.") from error
    default_port = ALLOWED_PORTS.get(parsed.scheme)
    if default_port is None or not parsed.host or parsed.userinfo:
        raise UnsafeDestinationError("Only http(s) URLs without credentials are allowed.")
    if parsed.port not in (None, default_port):
        raise UnsafeDestinationError("Only the default http(s) ports are allowed.")
    return parsed


class SafePdfFetcher(PdfFetcher):
    """Streams a PDF through `PinnedBackend` with a size cap and a bounded redirect chain.

    `timeout_seconds` bounds each network step (connect, each read); `deadline_seconds` bounds
    one whole download, so a host trickling bytes cannot hold an import open. A transient
    failure (timeout, network error, cut-off body, 429/5xx) is tried once more after
    `retry_delay_seconds`; refusals (401/403/404), non-PDFs, oversize files and unsafe
    destinations are never retried.
    """

    def __init__(
        self,
        *,
        max_bytes: int,
        max_redirects: int,
        timeout_seconds: float,
        user_agent: str,
        deadline_seconds: float | None = None,
        retry_delay_seconds: float = 1.0,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._timeout = timeout_seconds
        self._deadline = deadline_seconds or 3 * timeout_seconds
        self._retry_delay = retry_delay_seconds
        self._user_agent = user_agent
        self._backend = backend or PinnedBackend()

    async def fetch(self, url: str) -> bytes:
        """The PDF's bytes, or `PdfUnavailableError` with its reason in `details`."""
        try:
            return await self._download(url, probe=False)
        except PdfUnavailableError as error:
            if not is_transient(error):
                raise
        await anyio.sleep(self._retry_delay)
        return await self._download(url, probe=False)

    async def probe(self, url: str) -> ProbeResult:
        """Whether the URL answers with the start of a PDF; reads about 1 KB, no retry."""
        try:
            await self._download(url, probe=True)
        except PdfUnavailableError as error:
            return "unknown" if is_transient(error) else "failed"
        return "pdf"

    async def _download(self, url: str, *, probe: bool) -> bytes:
        try:
            with anyio.fail_after(self._deadline):
                async with httpcore.AsyncConnectionPool(
                    network_backend=self._backend, retries=0, max_connections=2
                ) as pool:
                    current = check_url(url)
                    for _ in range(self._max_redirects + 1):
                        result = await self._get(pool, current, probe=probe)
                        if isinstance(result, bytes):
                            return result
                        current = check_url(str(current.join(result)))
        except TimeoutError as error:
            raise unavailable("The download took too long.", "timeout") from error
        raise unavailable("Too many redirects.", "redirects")

    async def _get(
        self, pool: httpcore.AsyncConnectionPool, url: httpx.URL, *, probe: bool
    ) -> bytes | str:
        """The PDF's bytes (only the first ones when probing), or the redirect target."""
        headers = [(b"User-Agent", self._user_agent.encode()), (b"Accept", b"application/pdf")]
        if probe:
            headers.append((b"Range", f"bytes=0-{PDF_MAGIC_WINDOW - 1}".encode()))
        timeouts = {key: self._timeout for key in ("connect", "read", "write", "pool")}
        try:
            async with pool.stream(
                "GET", str(url), headers=headers, extensions={"timeout": timeouts}
            ) as response:
                if response.status in REDIRECT_STATUSES:
                    location = _header(response.headers, b"location")
                    if not location:
                        raise unavailable("Redirect without a location.", "redirects")
                    return location
                if response.status != 200 and not (probe and response.status == 206):
                    raise _status_failure(response.status)
                return await self._read(response, limit=PDF_MAGIC_WINDOW if probe else None)
        except httpcore.TimeoutException as error:
            raise unavailable("Timed out.", "timeout") from error
        except httpcore.UnsupportedProtocol as error:
            raise UnsafeDestinationError("Unsupported protocol.") from error
        except httpcore.NetworkError as error:
            raise unavailable(f"Download failed: {type(error).__name__}.", "network") from error
        except httpcore.ProtocolError as error:
            # e.g. the connection closed before Content-Length bytes arrived.
            raise unavailable(f"Download failed: {type(error).__name__}.", "incomplete") from error

    async def _read(self, response: httpcore.Response, *, limit: int | None) -> bytes:
        """The body (or its first `limit` bytes), refused past the size cap or if not a PDF."""
        length = _header(response.headers, b"content-length")
        if limit is None and length and length.isdigit() and int(length) > self._max_bytes:
            raise unavailable("The PDF is larger than the upload limit.", "too_large")
        body = bytearray()
        async for chunk in response.aiter_stream():
            body.extend(chunk)
            if limit is not None and len(body) >= limit:
                break
            if len(body) > self._max_bytes:
                raise unavailable("The PDF is larger than the upload limit.", "too_large")
        if PDF_MAGIC not in bytes(body[:PDF_MAGIC_WINDOW]):
            raise unavailable("The location did not return a PDF.", "not_pdf")
        return bytes(body)


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None
