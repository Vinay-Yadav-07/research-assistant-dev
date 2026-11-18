"""In-memory fake scholarly and web search."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from app.core.errors import PdfUnavailableError
from app.providers.fakes._text import coverage_score
from app.providers.fetch import PdfFetcher, ProbeResult, is_transient
from app.providers.search import (
    DiscoverySource,
    PaperRecord,
    ScholarlySearchProvider,
    WebResult,
    WebSearchProvider,
)

ItemT = TypeVar("ItemT")

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)

DEFAULT_PAPERS: tuple[PaperRecord, ...] = (
    PaperRecord(
        source="fake",
        external_id="fake-1",
        doi="10.5555/fake.0001",
        title="Porosity of electrospun PCL scaffolds and fibroblast infiltration",
        authors=["A. Example", "B. Sample"],
        year=2021,
        venue="Fake Journal of Tissue Engineering",
        abstract="Electrospun polycaprolactone scaffolds with higher porosity improved "
        "fibroblast infiltration and cell proliferation.",
        url="https://example.org/papers/fake-1",
        pdf_urls=["https://example.org/papers/fake-1.pdf"],
        citation_count=42,
    ),
    PaperRecord(
        source="fake",
        external_id="fake-2",
        doi="10.5555/fake.0002",
        title="Hydrogel stiffness guides mesenchymal stem cell differentiation",
        authors=["C. Placeholder"],
        year=2019,
        venue="Fake Biomaterials Letters",
        abstract="Stiffer hydrogels promoted osteogenic differentiation of mesenchymal stem "
        "cells, while soft hydrogels favoured adipogenic lineages.",
        url="https://example.org/papers/fake-2",
        citation_count=130,
    ),
    PaperRecord(
        source="fake",
        external_id="fake-3",
        doi="10.5555/fake.0003",
        title="3D bioprinting of vascularised cardiac tissue",
        authors=["D. Dummy", "E. Mock"],
        year=2023,
        venue="Fake Advanced Manufacturing",
        abstract="Bioprinted cardiac constructs with perfusable channels maintained "
        "cardiomyocyte viability for 28 days.",
        url="https://example.org/papers/fake-3",
        pdf_urls=["https://example.org/papers/fake-3.pdf"],
        citation_count=15,
    ),
    PaperRecord(
        source="fake",
        external_id="fake-4",
        doi="10.5555/fake.0004",
        title="Degradation rate of PLGA scaffolds in bone regeneration",
        authors=["F. Stand-in"],
        year=2020,
        venue="Fake Journal of Tissue Engineering",
        abstract="PLGA scaffolds degraded within twelve weeks and supported new bone "
        "formation in a rat calvarial defect model.",
        url="https://example.org/papers/fake-4",
        citation_count=58,
    ),
    PaperRecord(
        source="fake",
        external_id="fake-5",
        doi="10.5555/fake.0005",
        title="Electrospun scaffold fibre alignment directs neurite outgrowth",
        authors=["G. Surrogate"],
        year=2022,
        venue="Fake Neural Engineering",
        abstract="Aligned electrospun fibres increased neurite length compared with random "
        "fibre scaffolds.",
        url="https://example.org/papers/fake-5",
        pdf_urls=["https://example.org/papers/fake-5.pdf"],
        citation_count=27,
    ),
)

DEFAULT_WEB_RESULTS: tuple[WebResult, ...] = (
    WebResult(
        title="Overview of scaffold porosity in tissue engineering",
        url="https://example.org/web/scaffold-porosity",
        snippet="Scaffold porosity affects cell infiltration, nutrient diffusion, and "
        "mechanical strength.",
    ),
    WebResult(
        title="What is a hydrogel?",
        url="https://example.org/web/hydrogels",
        snippet="Hydrogels are water-swollen polymer networks used as soft tissue scaffolds.",
    ),
    WebResult(
        title="Introduction to bioprinting",
        url="https://example.org/web/bioprinting",
        snippet="Bioprinting deposits cells and biomaterials layer by layer to build tissue.",
    ),
)


@dataclass(frozen=True)
class SearchCall:
    """One recorded call, for asserting that (and how) a search provider was used."""

    method: str
    arguments: dict[str, Any]


def normalize_doi(doi: str) -> str:
    """Lower-case a DOI and strip resolver prefixes such as `https://doi.org/`."""
    value = doi.strip().lower()
    for prefix in _DOI_PREFIXES:
        value = value.removeprefix(prefix)
    return value


def _rank(query: str, items: Sequence[ItemT], text: Callable[[ItemT], str]) -> list[ItemT]:
    scored = [(coverage_score(query, text(item)), index, item) for index, item in enumerate(items)]
    return [item for score, _, item in sorted(scored, key=lambda s: (-s[0], s[1])) if score > 0]


def _paper_text(paper: PaperRecord) -> str:
    return f"{paper.title} {paper.abstract or ''}"


class FakeScholarlySearch(ScholarlySearchProvider):
    """Searches an in-memory catalog; records calls; can be told to fail (`fail_with`)."""

    def __init__(
        self,
        papers: Sequence[PaperRecord] = DEFAULT_PAPERS,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self._papers = tuple(papers)
        self.fail_with = fail_with
        self.calls: list[SearchCall] = []

    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        self._record("search", query=query, limit=limit, source=source)
        papers = [p for p in self._papers if p.pdf_urls or not open_access_only]
        return _rank(query, papers, _paper_text)[:limit]

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        self._record("get_by_doi", doi=doi)
        return self._find(doi)

    async def related(self, doi: str, *, limit: int) -> list[PaperRecord]:
        self._record("related", doi=doi, limit=limit)
        seed = self._find(doi)
        if seed is None:
            return []
        others = [paper for paper in self._papers if paper is not seed]
        return _rank(_paper_text(seed), others, _paper_text)[:limit]

    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        self._record("get_paper", source=source, external_id=external_id)
        return next((p for p in self._papers if p.external_id == external_id), None)

    def _find(self, doi: str) -> PaperRecord | None:
        wanted = normalize_doi(doi)
        return next(
            (p for p in self._papers if p.doi is not None and normalize_doi(p.doi) == wanted),
            None,
        )

    def _record(self, method: str, **arguments: Any) -> None:
        self.calls.append(SearchCall(method, arguments))
        if self.fail_with is not None:
            raise self.fail_with


class FakeWebSearch(WebSearchProvider):
    """Searches in-memory web results; records calls; can be told to fail (`fail_with`)."""

    def __init__(
        self,
        results: Sequence[WebResult] = DEFAULT_WEB_RESULTS,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self._results = tuple(results)
        self.fail_with = fail_with
        self.calls: list[SearchCall] = []

    async def search(self, query: str, *, limit: int) -> list[WebResult]:
        self.calls.append(SearchCall("search", {"query": query, "limit": limit}))
        if self.fail_with is not None:
            raise self.fail_with
        ranked = _rank(query, self._results, lambda r: f"{r.title} {r.snippet}")[:limit]
        return [
            result.model_copy(
                update={"score": coverage_score(query, f"{result.title} {result.snippet}")}
            )
            for result in ranked
        ]


class FakePdfFetcher(PdfFetcher):
    """Serves PDFs from a URL -> bytes (or exception) map; records every URL fetched."""

    def __init__(self, pdfs: dict[str, bytes | Exception] | None = None) -> None:
        self.pdfs = dict(pdfs or {})
        self.fetched: list[str] = []
        self.probed: list[str] = []

    async def fetch(self, url: str) -> bytes:
        self.fetched.append(url)
        result = self.pdfs.get(
            url, PdfUnavailableError("HTTP 404.", details={"reason": "not_found"})
        )
        if isinstance(result, Exception):
            raise result
        return result

    async def probe(self, url: str) -> ProbeResult:
        self.probed.append(url)
        result = self.pdfs.get(url)
        if isinstance(result, bytes):
            return "pdf"
        if isinstance(result, PdfUnavailableError) and is_transient(result):
            return "unknown"
        return "failed"
