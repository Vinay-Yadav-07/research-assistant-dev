import logging

import pytest

from app.providers.parser import ParsedPage
from app.services.page_cleanup import CleanedPages, remove_repeated_lines


def pages(*texts: str) -> list[ParsedPage]:
    return [ParsedPage(page_number=i, markdown=text) for i, text in enumerate(texts, start=1)]


def clean(items: list[ParsedPage], *, max_line_chars: int = 200) -> CleanedPages:
    return remove_repeated_lines(
        items, min_pages=3, min_page_fraction=0.5, max_line_chars=max_line_chars
    )


def test_running_header_and_page_numbers_are_removed() -> None:
    result = clean(
        pages(
            *(
                f"J Biomed Res. 2024; 12: {i}\n\nBody text {word}.\n\n{i}"
                for i, word in enumerate("abcd")
            )
        )
    )

    assert [page.markdown for page in result.pages] == [f"Body text {w}." for w in "abcd"]
    assert result.removed == {"j biomed res. #; #: #": 4, "#": 4}


def test_markup_and_spacing_do_not_hide_repeats() -> None:
    result = clean(
        pages("**Author  Manuscript**\nA", "Author Manuscript\nB", "_Author Manuscript_\nC")
    )

    assert [page.markdown for page in result.pages] == ["A", "B", "C"]


def test_heading_repeated_on_two_pages_is_kept() -> None:
    items = pages("## Results\nfirst", "## Results\nsecond", "## Discussion\nthird", "x\nfourth")

    result = clean(items)

    assert result.pages == items
    assert result.removed == {}


def test_numbered_headings_are_not_merged_by_digit_folding() -> None:
    items = pages(*(f"# Section {i}\nbody {w}" for i, w in enumerate("abcd")))

    assert clean(items).pages == items


def test_identical_heading_on_most_pages_is_removed() -> None:
    result = clean(pages(*(f"# Journal of Tissue Science\nbody {w}" for w in "abcd")))

    assert [page.markdown for page in result.pages] == [f"body {w}" for w in "abcd"]


def test_line_on_too_few_pages_is_kept() -> None:
    # 3 of 8 pages is below the 50% share.
    items = pages(*(["Draft\nx"] * 3 + [f"y{w}" for w in "abcde"]))

    assert clean(items).removed == {}


def test_short_documents_keep_everything() -> None:
    items = pages("Header\nA", "Header\nB")

    assert clean(items).pages == items


@pytest.mark.parametrize("line", ["|---|---|", "| 1 | 2 |"])
def test_table_rows_are_never_removed(line: str) -> None:
    items = pages(*(f"{line}\nrow {w}" for w in "abcd"))

    assert clean(items).pages == items


def test_long_lines_are_never_removed() -> None:
    long_line = "word " * 50
    items = pages(*(f"{long_line}\n{w}" for w in "abcd"))

    assert clean(items, max_line_chars=100).pages == items


def test_removed_lines_are_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.page_cleanup")

    clean(pages(*(f"Author Manuscript\n{w}" for w in "abcd")))

    records = [r for r in caplog.records if r.name == "app.services.page_cleanup"]
    assert [r.levelno for r in records] == [logging.DEBUG]
    assert "author manuscript" in records[0].getMessage()
    assert "4/4 pages" in records[0].getMessage()
