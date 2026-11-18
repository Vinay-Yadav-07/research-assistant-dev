"""OpenAlex and arXiv search for Discover against a mocked HTTP transport (no network)."""

from typing import Any

import httpx
import pytest

from app.core.errors import ExternalServiceError
from app.providers.live.scholarly import LiveScholarlySearch

PDF = "https://repo.example.org/paper.pdf"


def provider(answer: Any, seen: list[httpx.Request] | None = None) -> LiveScholarlySearch:
    """Every request gets `answer`: an int status, a JSON dict, or text (Atom XML)."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(answer, int):
            return httpx.Response(answer)
        if isinstance(answer, str):
            return httpx.Response(200, text=answer)
        return httpx.Response(200, json=answer)

    return LiveScholarlySearch(
        contact_email="team@example.org",
        timeout_seconds=5,
        transport=httpx.MockTransport(handle),
        retry_backoff_seconds=0,
    )


def work(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "https://openalex.org/W42",
        "doi": "https://doi.org/10.1000/ABC",
        "title": "Hydrogel <i>stiffness</i>",
        "publication_year": 2021,
        "authorships": [{"author": {"display_name": "A. Author"}}, {"author": {}}],
        "primary_location": {
            "source": {"display_name": "Biomaterials"},
            "landing_page_url": "https://journal.example.org/abc",
            "is_oa": False,
            "pdf_url": None,
        },
        "best_oa_location": None,
        "locations": [],
        "abstract_inverted_index": {"Soft": [0], "gels": [1], "differ": [2]},
        "cited_by_count": 7,
    }
    return {**base, **fields}


async def test_openalex_result_is_mapped() -> None:
    seen: list[httpx.Request] = []
    search = provider({"results": [work()]}, seen)

    [record] = await search.search("hydrogel stiffness", limit=5, source="openalex")

    assert record.source == "openalex"
    assert record.external_id == "W42"
    assert record.doi == "10.1000/abc"
    assert record.title == "Hydrogel stiffness"
    assert record.authors == ["A. Author"]
    assert (record.year, record.venue, record.citation_count) == (2021, "Biomaterials", 7)
    assert record.abstract == "Soft gels differ"
    assert record.url == "https://doi.org/10.1000/ABC"
    assert seen[0].url.params["search"] == "hydrogel stiffness"
    assert seen[0].url.params["mailto"] == "team@example.org"


async def test_openalex_without_a_pdf_location_is_link_only() -> None:
    landing_only = {"is_oa": True, "pdf_url": None, "landing_page_url": "https://x.org/a"}
    search = provider({"results": [work(best_oa_location=landing_only, locations=[landing_only])]})

    [record] = await search.search("q", limit=5, source="openalex")

    assert record.pdf_urls == []
    assert not record.importable


async def test_openalex_pdf_comes_from_any_open_access_location() -> None:
    locations = [
        {"is_oa": False, "pdf_url": "https://paywall.example.org/a.pdf"},
        {"is_oa": True, "pdf_url": "ftp://repo.example.org/a.pdf"},
        {"is_oa": True, "pdf_url": PDF},
        {"is_oa": True, "pdf_url": PDF},
        "not a location",
    ]
    search = provider({"results": [work(locations=locations)]})

    [record] = await search.search("q", limit=5, source="openalex")

    assert record.pdf_urls == [PDF]
    assert record.importable


async def test_openalex_best_location_comes_first() -> None:
    best = {"is_oa": True, "pdf_url": "https://best.example.org/a.pdf"}
    search = provider(
        {
            "results": [
                work(best_oa_location=best, locations=[{"is_oa": True, "pdf_url": PDF}, best])
            ]
        }
    )

    [record] = await search.search("q", limit=5, source="openalex")

    assert record.pdf_urls == ["https://best.example.org/a.pdf", PDF]


async def test_malformed_openalex_records_are_skipped() -> None:
    results = [
        work(title=None, display_name=None),
        work(id="not-an-openalex-id"),
        "junk",
        work(
            id="https://openalex.org/W7",
            doi=None,
            publication_year="2020",
            authorships="x",
            primary_location=None,
            abstract_inverted_index=[1],
            cited_by_count=None,
        ),
    ]
    [record] = await provider({"results": results}).search("q", limit=5, source="openalex")

    assert record.external_id == "W7"
    assert (record.doi, record.year, record.venue, record.abstract) == (None, None, None, None)
    assert record.url == "https://openalex.org/W7"


async def test_openalex_unexpected_body_gives_no_results() -> None:
    assert await provider({"results": "nope"}).search("q", limit=5, source="openalex") == []


async def test_openalex_failure_raises() -> None:
    with pytest.raises(ExternalServiceError):
        await provider(503).search("q", limit=5, source="openalex")


async def test_openalex_get_paper_validates_the_id() -> None:
    seen: list[httpx.Request] = []
    search = provider(work(), seen)

    record = await search.get_paper("openalex", "https://openalex.org/W42")

    assert record is not None and record.external_id == "W42"
    assert seen[0].url.path == "/works/W42"
    assert await search.get_paper("openalex", "../../admin") is None
    assert len(seen) == 1


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.01234v2</id>
    <published>2023-01-03T00:00:00Z</published>
    <title>Stiff   hydrogels
      and stem cells</title>
    <summary>We study &amp; report.</summary>
    <author><name>B. Writer</name></author>
    <author><name>C. Writer</name></author>
    <arxiv:doi>10.1000/XYZ</arxiv:doi>
    <arxiv:journal_ref>Acta Biomater. 12 (2023)</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/hep-th/9901001v1</id>
    <title>Old style</title>
  </entry>
</feed>"""


async def test_arxiv_entries_are_mapped_and_error_entries_skipped() -> None:
    seen: list[httpx.Request] = []

    records = await provider(ATOM, seen).search("The stiff hydrogels!", limit=5, source="arxiv")

    first, old = records
    assert first.external_id == "2301.01234v2"
    assert first.title == "Stiff hydrogels and stem cells"
    assert first.abstract == "We study & report."
    assert first.authors == ["B. Writer", "C. Writer"]
    assert (first.year, first.doi, first.venue) == (2023, "10.1000/xyz", "Acta Biomater. 12 (2023)")
    assert first.url == "https://arxiv.org/abs/2301.01234v2"
    assert first.pdf_urls == ["https://arxiv.org/pdf/2301.01234v2"]
    assert (old.external_id, old.venue, old.year) == ("hep-th/9901001v1", "arXiv", None)
    assert seen[0].url.params["search_query"] == "all:stiff AND all:hydrogels"


async def test_arxiv_query_without_words_makes_no_request() -> None:
    seen: list[httpx.Request] = []

    assert await provider(ATOM, seen).search("is it all?", limit=5, source="arxiv") == []
    assert seen == []


async def test_arxiv_xml_bombs_and_garbage_are_refused() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;">]><feed>&lol2;</feed>'
    )
    for body in (bomb, "not xml"):
        with pytest.raises(ExternalServiceError):
            await provider(body).search("q", limit=5, source="arxiv")


async def test_arxiv_get_paper_validates_the_id() -> None:
    seen: list[httpx.Request] = []
    search = provider(ATOM, seen)

    record = await search.get_paper("arxiv", "2301.01234v2")

    assert record is not None and record.external_id == "2301.01234v2"
    assert seen[0].url.params["id_list"] == "2301.01234v2"
    assert await search.get_paper("arxiv", "2301.01234 OR all:x") is None
    assert len(seen) == 1


# --- bounded retries (SRS §10.1: at most 2) ---


def sequence(*answers: Any, seen: list[httpx.Request]) -> LiveScholarlySearch:
    """Answers in order (the last repeats): an int status, a dict, or an exception to raise."""

    def handle(request: httpx.Request) -> httpx.Response:
        answer = answers[min(len(seen), len(answers) - 1)]
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, json=answer)

    return LiveScholarlySearch(
        contact_email=None,
        timeout_seconds=5,
        transport=httpx.MockTransport(handle),
        retry_backoff_seconds=0,
    )


@pytest.mark.parametrize(
    "transient", [503, 429, httpx.ReadTimeout("slow"), httpx.ConnectError("refused")]
)
async def test_lookup_retries_transient_failures(transient: Any) -> None:
    seen: list[httpx.Request] = []

    record = await sequence(transient, work(), seen=seen).get_paper("openalex", "W42")

    assert record is not None and len(seen) == 2


async def test_lookup_gives_up_after_one_retry_with_the_reason() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(ExternalServiceError) as error:
        await sequence(httpx.ReadTimeout("slow"), seen=seen).get_paper("openalex", "W42")

    assert len(seen) == 2
    assert error.value.details["reason"] == "timeout"


async def test_permanent_errors_are_not_retried() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(ExternalServiceError):
        await sequence(400, work(), seen=seen).search("q", limit=5, source="openalex")

    assert len(seen) == 1


async def test_open_access_only_filters_openalex() -> None:
    seen: list[httpx.Request] = []

    await sequence({"results": []}, seen=seen).search(
        "q", limit=5, source="openalex", open_access_only=True
    )

    assert seen[0].url.params["filter"] == "open_access.is_oa:true"


async def test_arxiv_retries_respect_the_rate_limiter() -> None:
    acquired = 0

    class CountingLimiter:
        async def acquire(self, tokens: int) -> None:
            nonlocal acquired
            acquired += 1

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, text=ATOM)

    search = LiveScholarlySearch(
        contact_email=None,
        timeout_seconds=5,
        transport=httpx.MockTransport(handle),
        arxiv_limiter=CountingLimiter(),  # type: ignore[arg-type]
        retry_backoff_seconds=0,
    )

    assert await search.get_paper("arxiv", "2301.01234v2") is not None
    assert acquired == len(seen) == 2


async def test_discover_requests_use_the_longer_timeout() -> None:
    timeouts: list[object] = []

    def handle(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={"results": []})

    search = LiveScholarlySearch(
        contact_email=None,
        timeout_seconds=5,
        discover_timeout_seconds=15,
        transport=httpx.MockTransport(handle),
    )

    await search.search("q", limit=5, source="openalex")
    await search.get_by_doi("10.1000/x")

    assert timeouts[0] == 15
    assert set(timeouts[1:]) == {5}  # DOI lookups during ingestion keep the short timeout


# --- OpenAlex API key and quota (D-080) ---


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def quota_provider(
    handle: Any, *, key: str | None = None, clock: Clock | None = None
) -> LiveScholarlySearch:
    return LiveScholarlySearch(
        contact_email="team@example.org",
        timeout_seconds=5,
        transport=httpx.MockTransport(handle),
        retry_backoff_seconds=0,
        openalex_api_key=key,
        clock=clock or Clock(),
    )


async def test_the_api_key_goes_to_openalex_in_a_header_only() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.crossref.org":
            return httpx.Response(404)
        if request.url.path.startswith("/works/doi:"):
            return httpx.Response(404)
        return httpx.Response(200, json={"results": []} if request.url.path == "/works" else work())

    search = quota_provider(handle, key="secret-key")
    await search.search("q", limit=5, source="openalex")
    await search.get_paper("openalex", "W42")
    await search.get_by_doi("10.1000/x")

    for request in seen:
        assert "secret-key" not in str(request.url)
        expected = "Bearer secret-key" if request.url.host == "api.openalex.org" else None
        assert request.headers.get("authorization") == expected, request.url


async def test_no_key_sends_no_authorization_header() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    await quota_provider(handle).search("q", limit=5, source="openalex")

    assert "authorization" not in seen[0].headers


def quota_answer(seen: list[httpx.Request], *, retry_after: str = "21234") -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/works":
            return httpx.Response(429, headers={"Retry-After": retry_after})
        return httpx.Response(200, json=work())

    return handle


async def test_a_used_up_quota_is_not_retried() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(ExternalServiceError) as error:
        await quota_provider(quota_answer(seen)).search("q", limit=5, source="openalex")

    assert len(seen) == 1
    assert error.value.details == {"reason": "quota_exhausted", "retry_after_seconds": 21234.0}


async def test_searches_pause_until_retry_after_but_lookups_continue() -> None:
    seen: list[httpx.Request] = []
    clock = Clock()
    search = quota_provider(quota_answer(seen), clock=clock)
    with pytest.raises(ExternalServiceError):
        await search.search("q", limit=5, source="openalex")

    clock.now += 100
    with pytest.raises(ExternalServiceError) as paused:
        await search.search("q", limit=5, source="openalex")
    assert len(seen) == 1  # no request while paused
    assert paused.value.details["reason"] == "quota_exhausted"
    assert paused.value.details["retry_after_seconds"] == pytest.approx(21134)

    assert await search.get_paper("openalex", "W42") is not None  # lookups cost no credits
    assert len(seen) == 2

    clock.now += 21234
    with pytest.raises(ExternalServiceError):
        await search.search("q", limit=5, source="openalex")
    assert len(seen) == 3  # asked again after the pause


async def test_a_short_retry_after_is_waited_out_and_retried() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"results": [work()]})

    assert len(await quota_provider(handle).search("q", limit=5, source="openalex")) == 1
    assert len(seen) == 2


async def test_a_retry_after_date_counts_as_a_used_up_quota() -> None:
    seen: list[httpx.Request] = []
    handle = quota_answer(seen, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")

    with pytest.raises(ExternalServiceError) as error:
        await quota_provider(handle).search("q", limit=5, source="openalex")

    assert error.value.details["reason"] == "quota_exhausted"
    assert len(seen) == 1
