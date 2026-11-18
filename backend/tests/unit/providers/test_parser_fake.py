import pytest

from app.core.errors import DocumentParseError, InvalidInputError
from app.providers.fakes import FakeParser


async def test_pages_are_split_on_form_feed_and_numbered_from_one() -> None:
    data = b"%PDF-fake\n# Introduction\nFirst page.\fSecond page.\f## Methods\nThird page."

    document = await FakeParser().parse(data)

    assert [page.page_number for page in document.pages] == [1, 2, 3]
    assert document.pages[0].markdown == "# Introduction\nFirst page."
    assert document.pages[2].markdown == "## Methods\nThird page."
    assert document.page_count == 3


async def test_max_pages_keeps_the_first_pages() -> None:
    document = await FakeParser().parse(b"one\ftwo\fthree", max_pages=2)

    assert [page.markdown for page in document.pages] == ["one", "two"]


async def test_header_is_optional() -> None:
    document = await FakeParser().parse(b"Only page.")

    assert [page.markdown for page in document.pages] == ["Only page."]


async def test_leading_metadata_lines_fill_metadata() -> None:
    data = (
        b"%PDF-fake\nTitle: Scaffold porosity\nAuthor: A. Example; B. Sample\n"
        b"Keywords: PCL, porosity\n# Abstract\nText.\n"
    )

    document = await FakeParser().parse(data)

    assert document.metadata.title == "Scaffold porosity"
    assert document.metadata.author == "A. Example; B. Sample"
    assert document.metadata.keywords == "PCL, porosity"
    assert document.metadata.subject is None
    assert document.pages[0].markdown == "# Abstract\nText."


async def test_metadata_lines_after_content_stay_in_the_text() -> None:
    document = await FakeParser().parse(b"Intro text.\nTitle: not metadata")

    assert document.metadata.title is None
    assert "Title: not metadata" in document.pages[0].markdown


async def test_blank_pages_are_kept() -> None:
    document = await FakeParser().parse(b"%PDF-fake\n\f  \f")

    assert [page.markdown for page in document.pages] == ["", "", ""]


async def test_invalid_utf8_raises_parse_error() -> None:
    with pytest.raises(DocumentParseError):
        await FakeParser().parse(b"%PDF-fake\n\xff\xfe\x00broken")


async def test_real_pdf_is_rejected_with_a_clear_message() -> None:
    with pytest.raises(DocumentParseError, match="PARSER_PROVIDER"):
        await FakeParser().parse(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj")


def test_parse_error_maps_to_invalid_input() -> None:
    assert issubclass(DocumentParseError, InvalidInputError)
