import pytest

from app.core.errors import ExternalServiceError, LLMQuotaExceededError
from app.providers.fakes import FakeLLM
from app.providers.parser import ParsedDocument, ParsedPage, PdfMetadata
from app.providers.search import DiscoverySource, PaperRecord
from app.services.document_metadata import (
    FirstPageExtractor,
    FirstPageMetadata,
    MetadataService,
    clean_text,
    doi_candidates,
    first_heading,
    normalize_doi,
    split_authors,
)


class StubLookup:
    """Knows some DOIs; records every lookup; can be made unavailable."""

    def __init__(self, known: dict[str, PaperRecord] | None = None, *, down: bool = False) -> None:
        self.known = known or {}
        self.down = down
        self.calls: list[str] = []

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        self.calls.append(doi)
        if self.down:
            raise ExternalServiceError("DOI lookup is unavailable.")
        return self.known.get(doi)

    async def search(
        self, query: str, *, limit: int, source: DiscoverySource, open_access_only: bool = False
    ) -> list[PaperRecord]:
        raise NotImplementedError

    async def related(self, doi: str, *, limit: int) -> list[PaperRecord]:
        raise NotImplementedError

    async def get_paper(self, source: DiscoverySource, external_id: str) -> PaperRecord | None:
        raise NotImplementedError


def record(doi: str, **fields: object) -> PaperRecord:
    values: dict[str, object] = {
        "source": "crossref",
        "external_id": doi,
        "doi": doi,
        "title": "Looked-up title",
        "authors": ["A. Author", "B. Author"],
        "year": 2023,
        "venue": "ChemRxiv",
    }
    values.update(fields)
    return PaperRecord.model_validate(values)


def document(
    *raw_pages: str, title: str | None = None, author: str | None = None
) -> ParsedDocument:
    pages = [
        ParsedPage(page_number=i, markdown=text, raw_text=text)
        for i, text in enumerate(raw_pages, start=1)
    ]
    return ParsedDocument(pages=pages, metadata=PdfMetadata(title=title, author=author))


def values(pages: ParsedDocument) -> list[tuple[str, bool]]:
    return [(c.value, c.at_line_end) for c in doi_candidates(pages.pages)]


# --- DOI candidates ---


def test_run_on_doi_ranks_after_the_line_end_one() -> None:
    doc = document(
        "https://doi.org/10.26434/chemrxiv.12924686.v1Tuneable Thiol-Ene Hydrogels\n"
        "Preprint DOI: 10.26434/chemrxiv.12924686.v1\n"
    )

    assert values(doc) == [
        ("10.26434/chemrxiv.12924686.v1", True),
        ("10.26434/chemrxiv.12924686.v1tuneable", False),
    ]


def test_only_pages_one_and_two_are_searched() -> None:
    doc = document("Title page", "doi: 10.1000/own.doi\n", "References\n10.1000/cited.paper\n")

    assert values(doc) == [("10.1000/own.doi", True)]


def test_duplicates_are_removed_and_case_is_folded() -> None:
    doc = document(
        "DOI 10.1016/J.TIBTECH.2023.02.002.\n", "https://doi.org/10.1016/j.tibtech.2023.02.002\n"
    )

    assert values(doc) == [("10.1016/j.tibtech.2023.02.002", True)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1016/j.tibtech.2023.02.002.", "10.1016/j.tibtech.2023.02.002"),
        ("10.1000/ABC,", "10.1000/abc"),
        ("10.1000/xyz);", "10.1000/xyz"),
        ("10.1016/S0140-6736(20)30183-5", "10.1016/s0140-6736(20)30183-5"),
        ("10.1016/S0140-6736(20)30183-5).", "10.1016/s0140-6736(20)30183-5"),
        ("10.1000/", None),
    ],
)
def test_normalize_doi(raw: str, expected: str | None) -> None:
    assert normalize_doi(raw) == expected


# --- PDF metadata ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "⠜Plasmonic Nanomaterials⠀: An emerging avenue",
            "Plasmonic Nanomaterials: An emerging avenue",
        ),
        ("  Hydrogels   for  tissue ", "Hydrogels for tissue"),
        ("Hydrogelsâ€™ design", None),
        ("CafÃ© scaffolds", None),
        ("Broken � title", None),
        ("Control\x07char", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_text(raw: str | None, expected: str | None) -> None:
    assert clean_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A. Smith; B. Jones", ["A. Smith", "B. Jones"]),
        (
            "Mohamadmahdi Samandari, Farnoosh Saeedinejad and Ali Tamayol",
            ["Mohamadmahdi Samandari", "Farnoosh Saeedinejad", "Ali Tamayol"],
        ),
        ("Solo Author", ["Solo Author"]),
        # Regression: the ';' of an escaped '&' used to split "amp" off as an author.
        ("A. Smith &amp; B. Jones", ["A. Smith", "B. Jones"]),
        (None, []),
    ],
)
def test_split_authors(raw: str | None, expected: list[str]) -> None:
    assert split_authors(raw) == expected


def test_title_falls_back_to_first_top_level_heading() -> None:
    pages = document(
        "## Journal banner\n\n# **Engineering Hydrogels for**\n# **Tissue Regeneration**\n\n"
        "Body.\n\n# Abstract"
    ).pages

    assert first_heading(pages) == "Engineering Hydrogels for Tissue Regeneration"


def test_title_fallback_uses_page_two_when_page_one_has_no_heading() -> None:
    assert first_heading(document("Cover text only.", "# Real Title\n\nBody").pages) == "Real Title"


def test_no_heading_means_no_title() -> None:
    assert first_heading(document("plain", "text", "# Too late").pages) is None


# --- MetadataService ---


async def test_confirmed_doi_enriches_and_overrides_pdf_metadata() -> None:
    lookup = StubLookup({"10.26434/chemrxiv-2023-t0vm9": record("10.26434/chemrxiv-2023-t0vm9")})
    doc = document("doi.org/10.26434/chemrxiv-2023-t0vm9\n", title="PDF title", author="Only Me")

    metadata = await MetadataService(lookup, max_candidates=3).extract(doc)

    assert metadata.doi == "10.26434/chemrxiv-2023-t0vm9"
    assert metadata.source == "crossref"
    assert metadata.title == "Looked-up title"
    assert metadata.authors == ["A. Author", "B. Author"]
    assert (metadata.year, metadata.venue) == (2023, "ChemRxiv")


async def test_pdf_fills_gaps_in_the_lookup() -> None:
    lookup = StubLookup({"10.1000/x": record("10.1000/x", title="", authors=[], venue=None)})
    doc = document("10.1000/x\n", title="PDF title", author="A; B")

    metadata = await MetadataService(lookup, max_candidates=3).extract(doc)

    assert (metadata.title, metadata.authors) == ("PDF title", ["A", "B"])


async def test_run_on_candidate_is_not_looked_up_when_a_line_end_one_confirms() -> None:
    good = "10.26434/chemrxiv.12924686.v1"
    lookup = StubLookup({good: record(good)})
    doc = document(f"https://doi.org/{good}Tuneable Hydrogels\nAbstract\n{good}\n")

    metadata = await MetadataService(lookup, max_candidates=3).extract(doc)

    assert metadata.doi == good
    assert lookup.calls == [good]


async def test_candidates_are_tried_until_one_is_confirmed() -> None:
    lookup = StubLookup({"10.1000/real": record("10.1000/real")})
    doc = document("10.1000/fake1\n10.1000/real\n")

    metadata = await MetadataService(lookup, max_candidates=3).extract(doc)

    assert lookup.calls == ["10.1000/fake1", "10.1000/real"]
    assert metadata.doi == "10.1000/real"


async def test_lookups_are_capped() -> None:
    lookup = StubLookup()
    doc = document("".join(f"10.1000/n{i}\n" for i in range(6)))

    metadata = await MetadataService(lookup, max_candidates=2).extract(doc)

    assert len(lookup.calls) == 2
    assert metadata.doi is None
    assert metadata.source == "pdf"


async def test_no_confirmed_doi_keeps_pdf_metadata_without_doi() -> None:
    doc = document("10.1000/unknown\n", title="PDF title")

    metadata = await MetadataService(StubLookup(), max_candidates=3).extract(doc)

    assert (metadata.title, metadata.doi, metadata.source) == ("PDF title", None, "pdf")


async def test_outage_keeps_pdf_metadata_and_stores_no_doi() -> None:
    lookup = StubLookup(down=True)
    doc = document("10.1000/own\n10.1000/second\n", title="PDF title", author="A, B")

    metadata = await MetadataService(lookup, max_candidates=3).extract(doc)

    assert lookup.calls == ["10.1000/own"]  # stops at the first failure
    assert metadata.doi is None
    assert (metadata.title, metadata.authors, metadata.source) == ("PDF title", ["A", "B"], "pdf")


async def test_outage_after_a_not_found_candidate_stores_no_doi() -> None:
    class FailsSecond(StubLookup):
        async def get_by_doi(self, doi: str) -> PaperRecord | None:
            self.calls.append(doi)
            if len(self.calls) > 1:
                raise ExternalServiceError("DOI lookup is unavailable.")
            return None

    lookup = FailsSecond()

    metadata = await MetadataService(lookup, max_candidates=3).extract(
        document("10.1000/first\n10.1000/second\n")
    )

    assert lookup.calls == ["10.1000/first", "10.1000/second"]
    assert metadata.doi is None


async def test_no_candidates_makes_no_lookup() -> None:
    lookup = StubLookup()

    metadata = await MetadataService(lookup, max_candidates=3).extract(
        document("No identifiers here.")
    )

    assert lookup.calls == []
    assert metadata.doi is None


# --- First-page LLM extraction (FR-04, D-068) ---

PAGE_ONE = "# Porous Scaffolds\n\nA. Author, B. Author\n\nBiomaterials 2022\n\nAbstract text."


def with_llm(lookup: StubLookup, llm: FakeLLM, *, max_chars: int = 6000) -> MetadataService:
    return MetadataService(
        lookup, max_candidates=3, first_page=FirstPageExtractor(llm, max_chars=max_chars)
    )


def page_one_reply(**fields: object) -> FirstPageMetadata:
    values: dict[str, object] = {
        "title": "Porous Scaffolds for Bone",
        "authors": ["A. Author", "B. Author"],
        "year": 2022,
        "venue": "Biomaterials",
    }
    values.update(fields)
    return FirstPageMetadata.model_validate(values)


async def test_confirmed_doi_makes_no_llm_call() -> None:
    lookup = StubLookup({"10.1000/x": record("10.1000/x")})
    llm = FakeLLM()

    metadata = await with_llm(lookup, llm).extract(document("10.1000/x\n" + PAGE_ONE))

    assert metadata.source == "crossref"
    assert llm.calls == []


async def test_without_a_confirmed_doi_the_llm_fields_replace_pdf_metadata() -> None:
    llm = FakeLLM(structured={FirstPageMetadata: [page_one_reply()]})
    doc = document(PAGE_ONE, title="Microsoft Word - draft3.docx", author="admin")

    metadata = await with_llm(StubLookup(), llm).extract(doc)

    assert metadata.title == "Porous Scaffolds for Bone"
    assert metadata.authors == ["A. Author", "B. Author"]
    assert (metadata.year, metadata.venue) == (2022, "Biomaterials")
    assert (metadata.doi, metadata.source) == (None, "llm")


async def test_lookup_outage_falls_through_to_the_llm_and_stores_no_doi() -> None:
    llm = FakeLLM(structured={FirstPageMetadata: [page_one_reply()]})

    metadata = await with_llm(StubLookup(down=True), llm).extract(
        document("10.1000/own\n" + PAGE_ONE)
    )

    assert (metadata.title, metadata.doi, metadata.source) == (
        "Porous Scaffolds for Bone",
        None,
        "llm",
    )


async def test_pdf_metadata_fills_fields_the_llm_left_empty() -> None:
    llm = FakeLLM(structured={FirstPageMetadata: [page_one_reply(authors=[], venue=None)]})
    doc = document(PAGE_ONE, author="C. Pdf; D. Pdf")

    metadata = await with_llm(StubLookup(), llm).extract(doc)

    assert metadata.title == "Porous Scaffolds for Bone"
    assert metadata.authors == ["C. Pdf", "D. Pdf"]
    assert metadata.venue is None


async def test_an_empty_llm_reply_keeps_pdf_metadata() -> None:
    empty = FirstPageMetadata(title="  ", authors=[""], year=None, venue=None)
    llm = FakeLLM(structured={FirstPageMetadata: [empty]})

    metadata = await with_llm(StubLookup(), llm).extract(document(PAGE_ONE, title="PDF title"))

    assert (metadata.title, metadata.source) == ("PDF title", "pdf")


@pytest.mark.parametrize(
    "reply",
    [
        LLMQuotaExceededError("Daily LLM quota reached."),
        {"title": "T", "authors": [], "year": 99999, "venue": None},
    ],
    ids=["provider-error", "invalid-output"],
)
async def test_llm_failure_keeps_pdf_metadata(reply: object) -> None:
    llm = FakeLLM(structured={FirstPageMetadata: [reply]})  # type: ignore[list-item]

    metadata = await with_llm(StubLookup(), llm).extract(document(PAGE_ONE, title="PDF title"))

    assert (metadata.title, metadata.source) == ("PDF title", "pdf")
    assert len(llm.calls) == 1


async def test_llm_reads_only_page_one_in_a_data_block_cut_to_the_limit() -> None:
    llm = FakeLLM(structured={FirstPageMetadata: [page_one_reply()]})
    doc = document("Page one text \x00here " + "x" * 100, "Page two must not be sent")

    await with_llm(StubLookup(), llm, max_chars=30).extract(doc)

    system, user = llm.calls[0].messages
    assert "extract bibliographic metadata" in system.content
    assert user.content.startswith("<first_page>\n") and user.content.endswith("</first_page>")
    assert "Page one text here" in user.content
    assert "\x00" not in user.content
    assert "Page two" not in user.content
    assert len(user.content) < 30 + len("<first_page>\n\n</first_page>") + 1
    assert llm.calls[0].temperature == 0


async def test_a_page_without_text_makes_no_llm_call() -> None:
    llm = FakeLLM()

    metadata = await with_llm(StubLookup(), llm).extract(document("   ", title="PDF title"))

    assert metadata.title == "PDF title"
    assert llm.calls == []


async def test_a_first_page_reply_has_no_doi_field() -> None:
    assert "doi" not in FirstPageMetadata.model_fields
