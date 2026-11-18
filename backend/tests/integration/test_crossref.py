"""Real DOI lookup against Crossref and OpenAlex (network). Sends CONTACT_EMAIL from
backend/.env if set. Skips, rather than fails, when either service returns 5xx or times out."""

from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.providers.live.scholarly import LiveScholarlySearch
from app.providers.search import PaperRecord

pytestmark = pytest.mark.integration


class OutageRecorder(httpx.AsyncBaseTransport):
    """The real transport, noting every 5xx response and timeout."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.outages: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            response = await self._inner.handle_async_request(request)
        except httpx.TimeoutException:
            self.outages.append(f"{request.url.host}: timeout")
            raise
        if response.status_code >= 500:
            self.outages.append(f"{request.url.host}: HTTP {response.status_code}")
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


Lookup = Callable[[str], Awaitable[PaperRecord | None]]


async def get_by_doi_or_skip(doi: str) -> PaperRecord | None:
    """`get_by_doi` that skips the test if Crossref or OpenAlex had an outage."""
    settings = Settings()
    recorder = OutageRecorder()
    search = LiveScholarlySearch(
        contact_email=settings.contact_email,
        timeout_seconds=settings.scholarly_timeout_seconds,
        transport=recorder,
    )
    try:
        record = await search.get_by_doi(doi)
    except ExternalServiceError:
        record = None
    if recorder.outages:
        pytest.skip(f"Scholarly API unavailable: {', '.join(recorder.outages)}")
    return record


@pytest.fixture
def lookup() -> Lookup:
    return get_by_doi_or_skip


async def test_known_doi_resolves_from_crossref(lookup: Lookup) -> None:
    record = await lookup("10.1016/j.jare.2021.11.006")

    assert record is not None
    assert record.source == "crossref"
    assert "Plasmonic Nanomaterials" in record.title
    assert record.authors[0] == "Yasaman-Sadat Borghei"
    assert (record.year, record.venue) == (2022, "Journal of Advanced Research")


async def test_footnote_digit_run_into_a_doi_is_unknown(lookup: Lookup) -> None:
    # The Advancements paper's DOI followed by a footnote "1"; Crossref and OpenAlex both 404.
    assert await lookup("10.26434/chemrxiv-2023-t0vm91") is None
