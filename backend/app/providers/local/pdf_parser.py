"""PDF parser backed by PyMuPDF4LLM: per-page Markdown with headings (FR-05)."""

import asyncio
import logging

import pymupdf
import pymupdf4llm  # type: ignore[import-untyped]

from app.core.errors import DocumentParseError, ScannedDocumentError
from app.providers.parser import DocumentParser, ParsedDocument, ParsedPage, PdfMetadata

logger = logging.getLogger(__name__)


class PyMuPDF4LLMParser(DocumentParser):
    """Rejects scanned PDFs, then converts each page to Markdown.

    `page_number` is the PDF page index (1-based), not the number printed on the page (D-054),
    because the source viewer opens pages by index.
    """

    def __init__(self, *, min_text_chars_per_page: int) -> None:
        self._min_text_chars_per_page = min_text_chars_per_page

    async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
        return await asyncio.to_thread(self._parse, data, max_pages)

    def _parse(self, data: bytes, max_pages: int | None) -> ParsedDocument:
        try:
            document = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        except Exception as exc:
            raise DocumentParseError("The file is not a readable PDF.") from exc
        with document:
            if document.needs_pass:
                raise DocumentParseError("The PDF is password-protected.")
            if document.page_count == 0:
                raise DocumentParseError("The PDF has no pages.")
            page_count = document.page_count
            if max_pages is not None:
                page_count = min(page_count, max_pages)
            texts = page_texts(document, page_count)
            self._check_text_layer(texts)
            try:
                # OCR stays off: scanned PDFs are rejected, not recognised (SRS §4).
                chunks = pymupdf4llm.to_markdown(
                    document,
                    pages=list(range(page_count)),
                    page_chunks=True,
                    use_ocr=False,
                    show_progress=False,
                )
            except Exception as exc:
                raise DocumentParseError("The PDF could not be converted to text.") from exc
            pages = [
                ParsedPage(page_number=index, markdown=chunk["text"].strip(), raw_text=text)
                for index, (chunk, text) in enumerate(zip(chunks, texts, strict=False), start=1)
            ]
            if len(pages) != page_count:
                raise DocumentParseError("The PDF's pages could not all be read.")
            return ParsedDocument(pages=pages, metadata=_metadata(document))

    def _check_text_layer(self, texts: list[str]) -> None:
        average = average_text_chars_per_page(texts)
        if average < self._min_text_chars_per_page:
            logger.info(
                "PDF rejected as scanned: %.0f text characters per page (minimum %d)",
                average,
                self._min_text_chars_per_page,
            )
            raise ScannedDocumentError()


def page_texts(document: pymupdf.Document, page_count: int | None = None) -> list[str]:
    """The raw text layer of each page (or the first `page_count`), with the PDF's line breaks."""
    texts: list[str] = []
    for index in range(document.page_count if page_count is None else page_count):
        text: str = document[index].get_text()  # type: ignore[no-untyped-call]
        texts.append(text)
    return texts


def average_text_chars_per_page(texts: list[str]) -> float:
    """Average count of non-whitespace characters per page."""
    total = sum(len(text) - sum(char.isspace() for char in text) for text in texts)
    return total / len(texts)


def _metadata(document: pymupdf.Document) -> PdfMetadata:
    raw = document.metadata or {}
    return PdfMetadata(
        title=_clean(raw.get("title")),
        author=_clean(raw.get("author")),
        subject=_clean(raw.get("subject")),
        keywords=_clean(raw.get("keywords")),
    )


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None
