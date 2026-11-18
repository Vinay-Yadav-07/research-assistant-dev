"""PyMuPDF4LLM parser on PDFs built in the test (no files, no network)."""

import pytest

from app.core.config import Settings
from app.core.errors import DocumentParseError, ScannedDocumentError
from app.providers.factory import build_parser
from app.providers.local.pdf_parser import PyMuPDF4LLMParser
from app.services.page_cleanup import remove_repeated_lines
from tests.unit.pdf_builder import BODY_SIZE, HEADING_SIZE, LOREM, Page, build_pdf

parser = PyMuPDF4LLMParser(min_text_chars_per_page=100)


async def test_pages_are_numbered_by_pdf_index_with_headings() -> None:
    pdf = build_pdf(
        [
            Page(blocks=[("Introduction", HEADING_SIZE), (LOREM, BODY_SIZE)]),
            Page(blocks=[("Methods", HEADING_SIZE), (LOREM, BODY_SIZE)]),
            Page(blocks=[(LOREM, BODY_SIZE)]),
        ],
        title=" Scaffold porosity ",
    )

    document = await parser.parse(pdf)

    assert [page.page_number for page in document.pages] == [1, 2, 3]
    assert document.pages[0].markdown.startswith("# Introduction")
    assert document.pages[1].markdown.startswith("# Methods")
    assert "Porous scaffolds" in document.pages[2].markdown
    assert document.metadata.title == "Scaffold porosity"
    assert document.metadata.author is None


async def test_max_pages_reads_only_the_first_pages() -> None:
    pdf = build_pdf(
        [
            Page(blocks=[("Introduction", HEADING_SIZE), (LOREM, BODY_SIZE)]),
            Page(blocks=[("Methods", HEADING_SIZE), (LOREM, BODY_SIZE)]),
            Page(blocks=[("Results", HEADING_SIZE), (LOREM, BODY_SIZE)]),
        ]
    )

    document = await parser.parse(pdf, max_pages=2)
    beyond = await parser.parse(pdf, max_pages=10)

    assert [page.page_number for page in document.pages] == [1, 2]
    assert document.pages[1].markdown.startswith("# Methods")
    assert beyond.page_count == 3


async def test_raw_text_keeps_the_pdf_line_breaks() -> None:
    pdf = build_pdf([Page(blocks=[("Introduction", HEADING_SIZE), (LOREM, BODY_SIZE)])])

    page = (await parser.parse(pdf)).pages[0]

    assert page.raw_text.splitlines()[0] == "Introduction"
    assert "Porous scaffolds" in page.raw_text
    assert page.raw_text != page.markdown


async def test_two_columns_are_read_left_then_right() -> None:
    left = " ".join(f"Alpha sentence {i}." for i in range(40))
    right = " ".join(f"Omega sentence {i}." for i in range(40))
    pdf = build_pdf([Page(blocks=[(LOREM, BODY_SIZE)], columns=(left, right))])

    markdown = (await parser.parse(pdf)).pages[0].markdown

    last_alpha = markdown.rindex("Alpha sentence")
    first_omega = markdown.index("Omega sentence")
    assert last_alpha < first_omega


async def test_image_only_pdf_is_rejected_as_scanned() -> None:
    pdf = build_pdf([Page(image_only=True), Page(image_only=True)])

    with pytest.raises(ScannedDocumentError) as error:
        await parser.parse(pdf)

    assert error.value.code == "document_scanned"


@pytest.mark.parametrize(("minimum", "scanned"), [(80, False), (200, True)])
async def test_scanned_threshold_is_average_text_per_page(minimum: int, scanned: bool) -> None:
    # LOREM has ~130 non-space characters per page.
    pdf = build_pdf([Page(blocks=[(LOREM, BODY_SIZE)]), Page(blocks=[(LOREM, BODY_SIZE)])])
    strict = PyMuPDF4LLMParser(min_text_chars_per_page=minimum)

    if scanned:
        with pytest.raises(ScannedDocumentError):
            await strict.parse(pdf)
    else:
        assert (await strict.parse(pdf)).page_count == 2


async def test_mostly_text_pdf_with_a_figure_page_is_accepted() -> None:
    pdf = build_pdf([Page(blocks=[(LOREM * 3, BODY_SIZE)]), Page(image_only=True)])

    assert (await parser.parse(pdf)).page_count == 2


@pytest.mark.parametrize("data", [b"", b"not a pdf", b"%PDF-1.7\n garbage"])
async def test_unreadable_bytes_raise_parse_error(data: bytes) -> None:
    with pytest.raises(DocumentParseError) as error:
        await parser.parse(data)

    assert not isinstance(error.value, ScannedDocumentError)


async def test_password_protected_pdf_is_rejected() -> None:
    pdf = build_pdf([Page(blocks=[(LOREM, BODY_SIZE)])], password="secret")

    with pytest.raises(DocumentParseError, match="password"):
        await parser.parse(pdf)


async def test_vertical_margin_text_is_dropped_by_the_parser() -> None:
    pdf = build_pdf([Page(blocks=[(LOREM, BODY_SIZE)], margin_text="Author Manuscript")])

    markdown = (await parser.parse(pdf)).pages[0].markdown

    assert "Author Manuscript" not in markdown
    assert "Porous scaffolds" in markdown


async def test_nih_footer_is_removed_by_cleanup() -> None:
    pages = [
        Page(
            blocks=[(f"Section {i}", HEADING_SIZE), (f"{LOREM} Topic {word}.", BODY_SIZE)],
            footer=f"Trends Biotechnol. Author manuscript; available in PMC 2026. Page {i + 1}",
        )
        for i, word in enumerate(["alpha", "beta", "gamma", "delta"])
    ]
    parsed = await parser.parse(build_pdf(pages))
    assert all("Author manuscript" in page.markdown for page in parsed.pages)

    cleaned = remove_repeated_lines(
        parsed.pages, min_pages=3, min_page_fraction=0.5, max_line_chars=200
    )

    assert not any("Author manuscript" in page.markdown for page in cleaned.pages)
    assert all("Porous scaffolds" in page.markdown for page in cleaned.pages)
    assert [page.markdown.splitlines()[0].strip() for page in cleaned.pages] == [
        f"# Section {i}" for i in range(4)
    ]


def test_factory_builds_pymupdf4llm_parser() -> None:
    settings = Settings(
        _env_file=None, parser_provider="pymupdf4llm", pdf_min_text_chars_per_page=42
    )

    built = build_parser(settings)

    assert isinstance(built, PyMuPDF4LLMParser)
