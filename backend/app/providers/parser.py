"""Document parser interface."""

from typing import Protocol

from pydantic import BaseModel, Field


class ParsedPage(BaseModel):
    """Text of one page as Markdown (headings preserved), plus the raw text layer."""

    page_number: int = Field(ge=1)
    markdown: str
    # Unformatted text with the PDF's line breaks (used to find DOIs); empty if unknown.
    raw_text: str = ""


class PdfMetadata(BaseModel):
    """Metadata embedded in the file itself; often missing or wrong, so S1 enriches it."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None


class ParsedDocument(BaseModel):
    """Parser output. Scanned PDFs are rejected by the parser; sections are found by the chunker."""

    pages: list[ParsedPage]
    metadata: PdfMetadata = Field(default_factory=PdfMetadata)

    @property
    def page_count(self) -> int:
        return len(self.pages)


class DocumentParser(Protocol):
    """Extracts per-page Markdown from a document's bytes."""

    async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
        """Parse the document, or raise `DocumentParseError` if it cannot be read.

        With `max_pages`, only the first pages are read (a fast look, e.g. the compatibility
        check). Raises `ScannedDocumentError` (a `DocumentParseError`) when there is no text layer.
        """
        ...
