"""Discover endpoints over HTTP: paper search and one-click import (FR-17, D-077).

Imports reuse the upload pipeline, so ownership, duplicates, compatibility and ingestion are
checked here through the same in-memory store and fakes as `test_documents_api.py`.
"""

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_paper_import_service, get_pdf_fetcher, get_providers
from app.core.config import Settings
from app.core.errors import ExternalServiceError, PdfUnavailableError
from app.main import create_app
from app.providers.factory import Providers, build_providers
from app.providers.fakes import FakePdfFetcher, FakeScholarlySearch
from app.providers.search import DiscoverySource, PaperRecord
from app.services.documents import DocumentService
from app.services.papers import PaperImportService, merge_results, search_papers
from app.services.topic_profile import TopicProfileService
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, ec_key
from tests.unit.storage_fakes import InMemoryFileStorage
from tests.unit.test_documents_api import (
    ALICE,
    BOB,
    COMPATIBILITY,
    RELATED_PDF,
    UNRELATED_PDF,
    InMemoryDocumentStore,
    Scheduled,
    bearer,
    compatibility_service,
    with_topic,
)

PDF_URL = "https://repo.example.org/open.pdf"
MIRROR_URL = "https://mirror.example.org/open.pdf"


def paper(
    external_id: str, *, pdfs: list[str], title: str = "Porous hydrogel scaffolds"
) -> PaperRecord:
    return PaperRecord(
        source="openalex",
        external_id=external_id,
        doi=f"10.1000/{external_id.lower()}",
        title=title,
        url=f"https://doi.org/10.1000/{external_id.lower()}",
        pdf_urls=pdfs,
    )


CATALOG = [
    paper("W1", pdfs=[PDF_URL]),
    paper("W2", pdfs=[], title="Hydrogel scaffold stiffness"),
    paper("W3", pdfs=[PDF_URL, MIRROR_URL], title="Scaffold porosity in hydrogels"),
]


class World:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = ec_key("test-key")
        self.store = InMemoryDocumentStore()
        self.storage = InMemoryFileStorage()
        self.scheduled = Scheduled()
        self.search = FakeScholarlySearch(CATALOG)
        self.fetcher = FakePdfFetcher({PDF_URL: RELATED_PDF})

    def service(self, *, budget_seconds: float = 120) -> PaperImportService:
        documents = DocumentService(
            self.store,
            self.storage,
            self.scheduled,
            profiles=TopicProfileService(self.store.profiles, COMPATIBILITY),
            signed_url_ttl_seconds=60,
        )
        return PaperImportService(
            self.search,
            self.fetcher,
            documents,
            compatibility_service(self.store, self.settings),
            download_budget_seconds=budget_seconds,
        )

    def headers(self, user: UUID = ALICE) -> dict[str, str]:
        return bearer(self.key, user)


@pytest.fixture
def world(settings: Settings) -> World:
    return World(settings)


@pytest.fixture
def api(world: World, settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[world.key]).verifier()
    providers = build_providers(settings)
    app.dependency_overrides[get_providers] = lambda: Providers(
        **{**providers.__dict__, "scholarly_search": world.search}
    )
    app.dependency_overrides[get_paper_import_service] = world.service
    app.dependency_overrides[get_pdf_fetcher] = lambda: world.fetcher
    with TestClient(app) as client:
        yield client


def import_paper(
    api: TestClient, world: World, workspace: UUID, external_id: str, **body: Any
) -> Any:
    return api.post(
        f"/api/v1/workspaces/{workspace}/import",
        json={"source": "openalex", "external_id": external_id, **body},
        headers=world.headers(body.pop("user", ALICE)),
    )


# --- search ---


def test_search_returns_results_with_importability(api: TestClient, world: World) -> None:
    response = api.get(
        "/api/v1/papers/search", params={"q": "hydrogel scaffolds"}, headers=world.headers()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unavailable"] == []
    by_id = {result["external_id"]: result for result in body["results"]}
    assert by_id["W1"]["importable"] is True
    assert by_id["W2"]["importable"] is False
    assert by_id["W3"]["pdf_urls"] == [PDF_URL, MIRROR_URL]
    assert {call.arguments["source"] for call in world.search.calls} == {"arxiv", "openalex"}


def test_search_one_source(api: TestClient, world: World) -> None:
    response = api.get(
        "/api/v1/papers/search",
        params={"q": "hydrogel", "source": "arxiv"},
        headers=world.headers(),
    )

    assert response.status_code == 200
    assert [call.arguments["source"] for call in world.search.calls] == ["arxiv"]


def test_search_with_every_source_down_is_502(api: TestClient, world: World) -> None:
    world.search.fail_with = ExternalServiceError("down")

    response = api.get("/api/v1/papers/search", params={"q": "hydrogel"}, headers=world.headers())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "external_service_error"


def test_search_needs_a_token_and_a_query(api: TestClient, world: World) -> None:
    assert api.get("/api/v1/papers/search", params={"q": "hydrogel"}).status_code == 401
    assert api.get("/api/v1/papers/search", headers=world.headers()).status_code == 422


class OneSourceDown(FakeScholarlySearch):
    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        if source == "arxiv":
            raise ExternalServiceError("arXiv is down")
        return await super().search(query, limit=limit, source=source)


async def search(provider: FakeScholarlySearch, fetcher: FakePdfFetcher | None = None) -> Any:
    return await search_papers(
        provider,
        fetcher or FakePdfFetcher(),
        "hydrogel",
        scope="all",
        limit=5,
        pdf_check_seconds=5,
    )


async def test_one_source_down_gives_partial_results() -> None:
    result = await search(OneSourceDown(CATALOG))

    assert result.unavailable == ["arxiv"]
    assert result.results


async def test_unexpected_errors_are_not_hidden_as_unavailable() -> None:
    with pytest.raises(RuntimeError):
        await search(FakeScholarlySearch(fail_with=RuntimeError("bug")))


def test_merge_interleaves_and_drops_repeats_keeping_the_importable_copy() -> None:
    arxiv_copy = paper(
        "2301.1", pdfs=["https://arxiv.org/pdf/2301.1"], title="Porous  Hydrogel scaffolds!"
    )
    openalex = [paper("W2", pdfs=[]), paper("W9", pdfs=[], title="Other")]
    arxiv = [arxiv_copy, paper("2301.2", pdfs=[], title="Third")]

    merged = merge_results([openalex, arxiv])

    assert [p.external_id for p in merged] == ["2301.1", "W9", "2301.2"]


async def test_listed_pdfs_that_do_not_answer_are_link_only() -> None:
    blocked = paper(
        "W5", pdfs=["https://publisher.example.org/blocked.pdf"], title="Blocked hydrogel"
    )
    fetcher = FakePdfFetcher({MIRROR_URL: RELATED_PDF})
    mirrored = paper("W6", pdfs=[PDF_URL, MIRROR_URL], title="Mirrored hydrogel")

    result = await search(FakeScholarlySearch([blocked, mirrored]), fetcher)

    by_id = {p.external_id: p for p in result.results}
    assert not by_id["W5"].importable
    assert by_id["W6"].pdf_urls == [MIRROR_URL, PDF_URL]  # the working copy first


async def test_arxiv_pdfs_are_trusted_without_a_check() -> None:
    preprint = PaperRecord(
        source="arxiv",
        external_id="2301.01234",
        title="Hydrogel preprint",
        pdf_urls=["https://arxiv.org/pdf/2301.01234"],
    )
    fetcher = FakePdfFetcher()

    result = await search(FakeScholarlySearch([preprint]), fetcher)

    assert result.results[0].importable
    assert fetcher.probed == []


class SlowFetcher(FakePdfFetcher):
    async def probe(self, url: str) -> bool:
        await asyncio.sleep(10)
        return True


async def test_pdf_checks_past_the_time_budget_stay_unverified() -> None:
    result = await search_papers(
        FakeScholarlySearch(CATALOG),
        SlowFetcher(),
        "hydrogel",
        scope="openalex",
        limit=5,
        pdf_check_seconds=0.05,
    )

    assert result.results
    assert all(p.pdf_status == "unverified" for p in result.results if p.importable)
    assert not any(p.pdf_verified for p in result.results)


# --- import ---


def test_import_stores_an_imported_document_and_ingests_it(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W1")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["duplicate"] is False and body["linked"] is True
    document = body["document"]
    assert document["source"] == "import"
    assert document["source_url"] == "https://doi.org/10.1000/w1"
    assert list(world.storage.objects.values()) == [RELATED_PDF]
    assert [call[2] for call in world.scheduled.calls] == [RELATED_PDF]
    assert world.fetcher.fetched == [PDF_URL]


def test_import_tries_the_next_location_when_one_fails(api: TestClient, world: World) -> None:
    world.fetcher.pdfs = {PDF_URL: PdfUnavailableError("HTTP 403."), MIRROR_URL: RELATED_PDF}
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W3")

    assert response.status_code == 202, response.text
    assert world.fetcher.fetched == [PDF_URL, MIRROR_URL]


def test_paper_without_a_pdf_is_not_imported(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W2")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_open_access"
    assert world.fetcher.fetched == []
    assert world.store.documents == {}


def test_no_downloadable_pdf_is_502_and_stores_nothing(api: TestClient, world: World) -> None:
    world.fetcher.pdfs = {}
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W3")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "pdf_unavailable"
    assert world.store.documents == {}


def test_unknown_paper_is_404(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(ALICE)

    assert import_paper(api, world, workspace, "W404").status_code == 404


def test_unrelated_paper_warns_until_imported_anyway(
    api: TestClient, world: World, settings: Settings
) -> None:
    world.fetcher.pdfs = {PDF_URL: UNRELATED_PDF}
    workspace = with_topic(world.store, settings, ALICE)

    warned = import_paper(api, world, workspace, "W1")

    assert warned.status_code == 409
    error = warned.json()["error"]
    assert error["code"] == "compatibility_warning"
    assert set(error["details"]) == {"score", "threshold"}
    assert world.store.documents == {}

    forced = import_paper(api, world, workspace, "W1", override=True)

    assert forced.status_code == 202, forced.text
    assert world.store.profiles.links[(workspace, UUID(forced.json()["document"]["id"]))].override


def test_related_paper_passes_the_compatibility_check(
    api: TestClient, world: World, settings: Settings
) -> None:
    workspace = with_topic(world.store, settings, ALICE)

    assert import_paper(api, world, workspace, "W1").status_code == 202


def test_reimport_is_a_duplicate(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(ALICE)
    first = import_paper(api, world, workspace, "W1")

    again = import_paper(api, world, workspace, "W1")

    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["document"]["id"] == first.json()["document"]["id"]
    assert len(world.scheduled.calls) == 1


def test_another_users_workspace_is_404_before_any_download(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(BOB)

    response = import_paper(api, world, workspace, "W1")

    assert response.status_code == 404
    assert world.fetcher.fetched == []
    assert world.search.calls == []


def test_import_needs_a_token(api: TestClient) -> None:
    response = api.post(
        f"/api/v1/workspaces/{uuid4()}/import",
        json={"source": "openalex", "external_id": "W1"},
    )

    assert response.status_code == 401


def test_import_rejects_unknown_sources(api: TestClient, world: World) -> None:
    workspace = world.store.add_workspace(ALICE)
    response = api.post(
        f"/api/v1/workspaces/{workspace}/import",
        json={"source": "google_scholar", "external_id": "x"},
        headers=world.headers(),
    )

    assert response.status_code == 422


# --- reliability (D-077 follow-up) ---


def unavailable(reason: str) -> PdfUnavailableError:
    return PdfUnavailableError(f"{reason}.", details={"reason": reason})


async def test_verification_drops_refused_links_and_keeps_inconclusive_ones() -> None:
    refused = paper("W7", pdfs=[PDF_URL], title="Refused hydrogel")
    flaky = paper("W8", pdfs=[MIRROR_URL], title="Flaky hydrogel")
    fetcher = FakePdfFetcher(
        {PDF_URL: unavailable("access_denied"), MIRROR_URL: unavailable("timeout")}
    )

    result = await search(FakeScholarlySearch([refused, flaky]), fetcher)

    by_id = {p.external_id: p for p in result.results}
    assert by_id["W7"].pdf_status == "none"
    assert by_id["W8"].pdf_status == "unverified"
    assert by_id["W8"].pdf_urls == [MIRROR_URL]


async def test_verified_location_moves_first() -> None:
    alt = paper("W9", pdfs=[PDF_URL, MIRROR_URL], title="Alternative hydrogel")
    fetcher = FakePdfFetcher({PDF_URL: unavailable("access_denied"), MIRROR_URL: RELATED_PDF})

    [result] = (await search(FakeScholarlySearch([alt]), fetcher)).results

    assert result.pdf_status == "verified"
    assert result.pdf_urls == [MIRROR_URL, PDF_URL]


async def test_importable_only_asks_for_open_access_and_drops_link_only_papers() -> None:
    provider = FakeScholarlySearch(CATALOG)
    fetcher = FakePdfFetcher({PDF_URL: RELATED_PDF})

    result = await search_papers(
        provider,
        fetcher,
        "hydrogel scaffolds",
        scope="openalex",
        limit=5,
        pdf_check_seconds=5,
        importable_only=True,
    )

    assert result.results and all(p.importable for p in result.results)
    assert "W2" not in {p.external_id for p in result.results}


def test_search_route_passes_importable_only(api: TestClient, world: World) -> None:
    response = api.get(
        "/api/v1/papers/search",
        params={"q": "hydrogel scaffolds", "source": "openalex", "importable_only": "true"},
        headers=world.headers(),
    )

    assert response.status_code == 200, response.text
    assert {r["external_id"] for r in response.json()["results"]} == {"W1", "W3"}
    assert all(r["pdf_status"] == "verified" for r in response.json()["results"])


def test_probe_ok_but_full_download_failing_is_a_retryable_502(
    api: TestClient, world: World
) -> None:
    # The search check read the first 1 KB; the full download then timed out.
    world.fetcher.pdfs = {PDF_URL: unavailable("timeout")}
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W1")

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "pdf_unavailable"
    assert error["details"]["reason"] == "timeout"
    assert error["details"]["retryable"] is True
    assert error["details"]["attempts"] == [{"host": "repo.example.org", "reason": "timeout"}]
    assert world.store.documents == {}


def test_publisher_refusals_are_not_retryable(api: TestClient, world: World) -> None:
    world.fetcher.pdfs = {
        PDF_URL: unavailable("access_denied"),
        MIRROR_URL: unavailable("access_denied"),
    }
    workspace = world.store.add_workspace(ALICE)

    error = import_paper(api, world, workspace, "W3").json()["error"]

    assert error["details"]["reason"] == "access_denied"
    assert error["details"]["retryable"] is False
    assert world.fetcher.fetched == [PDF_URL, MIRROR_URL]


def test_a_transient_failure_anywhere_makes_the_import_retryable(
    api: TestClient, world: World
) -> None:
    world.fetcher.pdfs = {PDF_URL: unavailable("access_denied"), MIRROR_URL: unavailable("network")}
    workspace = world.store.add_workspace(ALICE)

    error = import_paper(api, world, workspace, "W3").json()["error"]

    assert (error["details"]["reason"], error["details"]["retryable"]) == ("network", True)


def test_import_falls_back_to_an_alternative_location_after_a_403(
    api: TestClient, world: World
) -> None:
    world.fetcher.pdfs = {PDF_URL: unavailable("access_denied"), MIRROR_URL: RELATED_PDF}
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W3")

    assert response.status_code == 202, response.text
    assert world.fetcher.fetched == [PDF_URL, MIRROR_URL]


class LookupDown(FakeScholarlySearch):
    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        raise ExternalServiceError("Timed out.", details={"reason": "timeout"})


def test_source_lookup_timeout_is_a_clear_retryable_error(api: TestClient, world: World) -> None:
    world.search = LookupDown(CATALOG)
    workspace = world.store.add_workspace(ALICE)

    response = import_paper(api, world, workspace, "W1")

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "source_unavailable"
    assert error["details"] == {"source": "openalex", "reason": "timeout"}
    assert world.fetcher.fetched == []


class HangingFetcher(FakePdfFetcher):
    async def fetch(self, url: str) -> bytes:
        self.fetched.append(url)
        await asyncio.sleep(10)
        return RELATED_PDF


async def test_the_import_budget_bounds_all_locations(world: World) -> None:
    world.fetcher = HangingFetcher()
    service = world.service(budget_seconds=0.05)
    workspace = world.store.add_workspace(ALICE)

    with pytest.raises(PdfUnavailableError) as error:
        await service.import_paper(ALICE, workspace, "openalex", "W3")

    assert error.value.details["reason"] == "timeout"
    assert error.value.details["retryable"] is True
    assert world.fetcher.fetched == [PDF_URL]


# --- OpenAlex quota (D-080) ---


class OpenAlexQuotaUsedUp(FakeScholarlySearch):
    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        if source == "openalex":
            raise ExternalServiceError(
                "quota", details={"reason": "quota_exhausted", "retry_after_seconds": 3600}
            )
        return await super().search(query, limit=limit, source=source)

    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        if source == "openalex":
            raise ExternalServiceError("quota", details={"reason": "quota_exhausted"})
        return await super().get_paper(source, external_id)


async def test_a_used_up_openalex_quota_still_returns_arxiv_results() -> None:
    preprint = PaperRecord(
        source="arxiv",
        external_id="2301.1",
        title="Hydrogel preprint",
        pdf_urls=["https://arxiv.org/pdf/2301.1"],
    )

    result = await search(OpenAlexQuotaUsedUp([preprint]))

    assert [p.external_id for p in result.results] == ["2301.1"]
    assert result.unavailable == ["openalex"]
    assert result.quota_exhausted == ["openalex"]


def test_import_lookup_with_a_used_up_quota_says_so(api: TestClient, world: World) -> None:
    world.search = OpenAlexQuotaUsedUp(CATALOG)
    workspace = world.store.add_workspace(ALICE)

    error = import_paper(api, world, workspace, "W1").json()["error"]

    assert error["code"] == "source_unavailable"
    assert error["details"]["reason"] == "quota_exhausted"
