"""Crossref/OpenAlex DOI lookup against a mocked HTTP transport (no network)."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.errors import ExternalServiceError, ProviderConfigurationError
from app.providers.live.scholarly import LiveScholarlySearch

DOI = "10.1016/j.jare.2021.11.006"
CROSSREF_WORK = {
    "status": "ok",
    "message": {
        "DOI": "10.1016/J.JARE.2021.11.006",
        "type": "journal-article",
        "title": ["“Plasmonic <i>Nanomaterials</i>”: an emerging avenue"],
        "author": [
            {"given": "Yasaman-Sadat", "family": "Borghei"},
            {"given": "Saman", "family": "Hosseinkhani"},
            {"name": "Consortium &amp; Partners"},
        ],
        "container-title": ["Journal of Advanced Research"],
        "issued": {"date-parts": [[2022, 7]]},
        "URL": "https://doi.org/10.1016/j.jare.2021.11.006",
    },
}
OPENALEX_WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1016/j.jare.2021.11.006",
    "title": "Plasmonic Nanomaterials",
    "publication_year": 2022,
    "authorships": [{"author": {"display_name": "Yasaman-Sadat Borghei"}}],
    "primary_location": {"source": {"display_name": "Journal of Advanced Research"}},
}

Handler = Callable[[httpx.Request], httpx.Response]


def provider(handler: Handler, email: str | None = "team@example.org") -> LiveScholarlySearch:
    return LiveScholarlySearch(
        contact_email=email, timeout_seconds=5, transport=httpx.MockTransport(handler)
    )


def routes(crossref: Any, openalex: Any, seen: list[httpx.Request] | None = None) -> Handler:
    """Answer per host: an int status, a JSON dict (200), or an exception to raise."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answer = crossref if request.url.host == "api.crossref.org" else openalex
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer)
        if isinstance(answer, str):
            return httpx.Response(200, text=answer)
        return httpx.Response(200, json=answer)

    return handle


async def test_crossref_record_is_mapped() -> None:
    record = await provider(routes(CROSSREF_WORK, 500)).get_by_doi(DOI)

    assert record is not None
    assert record.source == "crossref"
    assert record.doi == DOI
    assert record.title == "“Plasmonic Nanomaterials”: an emerging avenue"
    assert record.authors == [
        "Yasaman-Sadat Borghei",
        "Saman Hosseinkhani",
        "Consortium & Partners",
    ]
    assert (record.year, record.venue) == (2022, "Journal of Advanced Research")


async def test_requests_identify_the_contact_email() -> None:
    seen: list[httpx.Request] = []

    await provider(routes(CROSSREF_WORK, 500, seen)).get_by_doi(DOI.upper())

    request = seen[0]
    assert request.url.path == f"/works/{DOI}"
    assert request.url.params["mailto"] == "team@example.org"
    assert request.headers["User-Agent"].endswith("(mailto:team@example.org)")


async def test_no_email_is_sent_when_none_is_configured() -> None:
    seen: list[httpx.Request] = []

    await provider(routes(CROSSREF_WORK, 500, seen), email=None).get_by_doi(DOI)

    assert "mailto" not in seen[0].url.params
    assert "mailto" not in seen[0].headers["User-Agent"]


async def test_crossref_404_falls_back_to_openalex() -> None:
    seen: list[httpx.Request] = []

    record = await provider(routes(404, OPENALEX_WORK, seen)).get_by_doi(DOI)

    assert record is not None
    assert record.source == "openalex"
    assert record.doi == DOI
    assert record.authors == ["Yasaman-Sadat Borghei"]
    assert seen[1].url.path == f"/works/doi:{DOI}"


@pytest.mark.parametrize(
    "crossref",
    [503, httpx.ConnectTimeout("slow"), httpx.ConnectError("down"), "not json", {"message": []}],
    ids=["5xx", "timeout", "connect-error", "invalid-json", "unexpected-shape"],
)
async def test_crossref_failure_falls_back_to_openalex(crossref: Any) -> None:
    record = await provider(routes(crossref, OPENALEX_WORK)).get_by_doi(DOI)

    assert record is not None
    assert record.source == "openalex"


async def test_unknown_everywhere_is_none() -> None:
    assert await provider(routes(404, 404)).get_by_doi(DOI) is None


@pytest.mark.parametrize(
    ("crossref", "openalex"),
    [(httpx.ReadTimeout("slow"), 404), (404, 504), (500, httpx.ConnectError("down"))],
)
async def test_failure_without_a_match_raises(crossref: Any, openalex: Any) -> None:
    with pytest.raises(ExternalServiceError) as error:
        await provider(routes(crossref, openalex)).get_by_doi(DOI)

    assert error.value.details["doi"] == DOI


async def test_preprint_without_container_title_gets_server_name() -> None:
    work = {
        "message": {
            "DOI": "10.26434/chemrxiv-2023-t0vm9",
            "type": "posted-content",
            "title": ["Advancements"],
            "container-title": [],
            "posted": {"date-parts": [[2023, 5, 18]]},
        }
    }

    record = await provider(routes(work, 500)).get_by_doi("10.26434/chemrxiv-2023-t0vm9")

    assert record is not None
    assert (record.venue, record.year) == ("ChemRxiv", 2023)


async def test_related_papers_are_not_implemented_yet() -> None:
    search = provider(routes(404, 404))

    with pytest.raises(ProviderConfigurationError, match="Phase 5"):
        await search.related(DOI, limit=5)
