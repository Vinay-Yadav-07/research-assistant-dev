import pytest

from app.core.errors import ExternalServiceError
from app.providers.fakes import FakeScholarlySearch, FakeWebSearch, SearchCall
from app.providers.fakes.search import DEFAULT_PAPERS, normalize_doi
from app.providers.search import PaperRecord


async def test_search_ranks_matching_papers_and_respects_limit() -> None:
    search = FakeScholarlySearch()

    results = await search.search("electrospun scaffold", limit=2, source="openalex")

    assert len(results) == 2
    assert {paper.external_id for paper in results} <= {"fake-1", "fake-5"}


async def test_search_without_matches_returns_nothing() -> None:
    assert (
        await FakeScholarlySearch().search("quantum chromodynamics", limit=5, source="openalex")
        == []
    )


async def test_custom_catalog_is_used() -> None:
    paper = PaperRecord(source="fake", external_id="x", doi="10.5555/x", title="Graphene inks")

    results = await FakeScholarlySearch([paper]).search("graphene", limit=5, source="openalex")

    assert results == [paper]


@pytest.mark.parametrize(
    "doi",
    [
        "10.5555/fake.0002",
        "10.5555/FAKE.0002",
        "https://doi.org/10.5555/fake.0002",
        "doi:10.5555/fake.0002",
    ],
)
async def test_get_by_doi_normalises_the_doi(doi: str) -> None:
    paper = await FakeScholarlySearch().get_by_doi(doi)

    assert paper is not None
    assert paper.external_id == "fake-2"


async def test_unknown_doi_returns_none() -> None:
    search = FakeScholarlySearch()

    assert await search.get_by_doi("10.5555/missing") is None
    assert await search.get_paper("openalex", "missing") is None
    assert await search.related("10.5555/missing", limit=3) == []


async def test_related_excludes_the_seed_paper() -> None:
    results = await FakeScholarlySearch().related("10.5555/fake.0001", limit=5)

    assert results
    assert all(paper.external_id != "fake-1" for paper in results)
    assert results[0].external_id == "fake-5"


async def test_get_paper_returns_the_record_and_its_pdf_locations() -> None:
    search = FakeScholarlySearch()

    paper = await search.get_paper("openalex", "fake-1")
    link_only = await search.get_paper("openalex", "fake-2")

    assert paper == DEFAULT_PAPERS[0]
    assert paper.importable
    assert link_only is not None
    assert not link_only.importable


async def test_scholarly_calls_are_recorded() -> None:
    search = FakeScholarlySearch()

    await search.search("scaffold", limit=3, source="openalex")
    await search.get_by_doi("10.5555/fake.0001")

    assert search.calls == [
        SearchCall("search", {"query": "scaffold", "limit": 3, "source": "openalex"}),
        SearchCall("get_by_doi", {"doi": "10.5555/fake.0001"}),
    ]


async def test_scholarly_failure_is_raised_and_recorded() -> None:
    search = FakeScholarlySearch(fail_with=ExternalServiceError("rate limited"))

    with pytest.raises(ExternalServiceError, match="rate limited"):
        await search.search("scaffold", limit=3, source="openalex")
    assert len(search.calls) == 1


async def test_web_search_ranks_and_scores_results() -> None:
    results = await FakeWebSearch().search("scaffold porosity", limit=5)

    assert results[0].url == "https://example.org/web/scaffold-porosity"
    assert results[0].score == 1.0
    assert all(result.score is not None and result.score > 0 for result in results)


async def test_web_search_records_calls_and_can_fail() -> None:
    web = FakeWebSearch(fail_with=ExternalServiceError("down"))

    with pytest.raises(ExternalServiceError):
        await web.search("hydrogel", limit=1)
    assert web.calls == [SearchCall("search", {"query": "hydrogel", "limit": 1})]


def test_normalize_doi() -> None:
    assert normalize_doi("  HTTPS://DX.DOI.ORG/10.5555/ABC ") == "10.5555/abc"
