"""Search provider interfaces: scholarly APIs and (approval-gated) web search.

The two are separate so that code without an approval for Corpus + Web mode is never handed a
`WebSearchProvider` at all (D-032).
"""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, computed_field

ScholarlySource = Literal[
    "openalex", "semantic_scholar", "arxiv", "europe_pmc", "crossref", "unpaywall", "fake"
]
# Sources the Discover page searches and imports from (D-077).
DiscoverySource = Literal["arxiv", "openalex"]


class PaperRecord(BaseModel):
    """One paper from a scholarly API; mirrors the `external_sources` table."""

    source: ScholarlySource
    external_id: str
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    # Open-access PDF locations, best first; empty when only a landing page is known.
    pdf_urls: list[str] = Field(default_factory=list)
    # True once the first PDF location answered with a PDF during search (Discover).
    pdf_verified: bool = False
    citation_count: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def importable(self) -> bool:
        """True when a PDF location is known; import still downloads and checks it."""
        return bool(self.pdf_urls)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pdf_status(self) -> Literal["verified", "unverified", "none"]:
        """`verified`: a PDF answered; `unverified`: a PDF link not checked, or the check was
        inconclusive; `none`: link only."""
        if not self.pdf_urls:
            return "none"
        return "verified" if self.pdf_verified else "unverified"


class WebResult(BaseModel):
    """One general web search result."""

    title: str
    url: str
    snippet: str
    score: float | None = None


class ScholarlySearchProvider(Protocol):
    """Access to scholarly metadata APIs (OpenAlex, Semantic Scholar, arXiv, Europe PMC, ...)."""

    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        """Search one source by free-text query, best matches first.

        `open_access_only` asks the source for open-access works only (arXiv always is).
        """
        ...

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        """Look up one paper by DOI; `None` if unknown."""
        ...

    async def related(self, doi: str, *, limit: int) -> list[PaperRecord]:
        """Papers related to the given one, excluding the paper itself."""
        ...

    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        """One paper by its id at the source (with its PDF locations); None if unknown."""
        ...


class WebSearchProvider(Protocol):
    """General web search. Only used after Corpus + Web approval."""

    async def search(self, query: str, *, limit: int) -> list[WebResult]:
        """Search the web, best matches first."""
        ...
