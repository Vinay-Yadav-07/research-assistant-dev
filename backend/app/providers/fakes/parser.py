"""Fake parser for a simple text format that tests can write by hand.

Format (UTF-8):

    %PDF-fake                  <- optional first line, so PDF type checks pass
    Title: Scaffold porosity   <- optional metadata lines (Title, Author, Subject, Keywords)
    # Introduction
    page one text
    \\f                         <- form feed separates pages
    page two text
"""

import re

from app.core.errors import DocumentParseError
from app.providers.parser import DocumentParser, ParsedDocument, ParsedPage, PdfMetadata

FAKE_PDF_HEADER = b"%PDF-fake"
_REAL_PDF_HEADER = b"%PDF-"
_METADATA_LINE = re.compile(r"^(Title|Author|Subject|Keywords):[ \t]*(.*)$")
_PAGE_BREAK = "\f"


class FakeParser(DocumentParser):
    """Parses the fake text format; real PDFs are rejected with a clear message."""

    async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
        if data.startswith(FAKE_PDF_HEADER):
            data = data[len(FAKE_PDF_HEADER) :].removeprefix(b"\r").removeprefix(b"\n")
        elif data.startswith(_REAL_PDF_HEADER):
            raise DocumentParseError(
                "The fake parser cannot read real PDFs; set PARSER_PROVIDER to a real parser."
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("The document is not valid UTF-8 text.") from exc

        metadata, body = _split_metadata(text)
        pages = [
            ParsedPage(page_number=number, markdown=page.strip(), raw_text=page)
            for number, page in enumerate(body.split(_PAGE_BREAK), start=1)
        ]
        if max_pages is not None:
            pages = pages[:max_pages]
        return ParsedDocument(pages=pages, metadata=metadata)


def _split_metadata(text: str) -> tuple[PdfMetadata, str]:
    fields: dict[str, str] = {}
    lines = text.split("\n")
    consumed = 0
    for line in lines:
        match = _METADATA_LINE.match(line.rstrip("\r"))
        if match is None:
            break
        fields[match.group(1).lower()] = match.group(2).strip()
        consumed += 1
    return PdfMetadata.model_validate(fields), "\n".join(lines[consumed:])
