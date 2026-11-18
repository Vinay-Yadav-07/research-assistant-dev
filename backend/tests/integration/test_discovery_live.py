"""Real Discover search and PDF download (network): arXiv, OpenAlex, and the safe fetcher.

Checks the parts mocks cannot: the live response formats and that TLS through the pinned
backend verifies certificates against the host name. Skips when a service is unreachable.
"""

import pytest

from app.core.config import Settings
from app.core.errors import ExternalServiceError, PdfUnavailableError
from app.providers.live.safe_fetch import SafePdfFetcher, UnsafeDestinationError
from app.providers.live.scholarly import LiveScholarlySearch, user_agent

pytestmark = pytest.mark.integration


@pytest.fixture
def search(settings: Settings) -> LiveScholarlySearch:
    return LiveScholarlySearch(contact_email=settings.contact_email, timeout_seconds=15)


@pytest.fixture
def fetcher(settings: Settings) -> SafePdfFetcher:
    return SafePdfFetcher(
        max_bytes=25 * 1024 * 1024,
        max_redirects=3,
        timeout_seconds=30,
        user_agent=user_agent(settings.contact_email),
    )


async def test_arxiv_search_and_pdf_download(
    search: LiveScholarlySearch, fetcher: SafePdfFetcher
) -> None:
    try:
        results = await search.search("attention is all you need", limit=3, source="arxiv")
    except ExternalServiceError as error:
        pytest.skip(f"arXiv unavailable: {error.message}")
    assert results and all(paper.importable for paper in results)

    paper = await search.get_paper("arxiv", results[0].external_id)
    assert paper is not None
    try:
        data = await fetcher.fetch(paper.pdf_urls[0])
    except PdfUnavailableError as error:
        if isinstance(error, UnsafeDestinationError):
            raise
        pytest.skip(f"arXiv PDF unavailable: {error.message}")
    assert data.startswith(b"%PDF-")


async def test_openalex_search_finds_open_access_pdfs(search: LiveScholarlySearch) -> None:
    try:
        results = await search.search("hydrogel stiffness stem cell", limit=10, source="openalex")
    except ExternalServiceError as error:
        pytest.skip(f"OpenAlex unavailable: {error.message}")
    assert results
    assert all(url.startswith("http") for paper in results for url in paper.pdf_urls)
    assert any(paper.importable for paper in results)
