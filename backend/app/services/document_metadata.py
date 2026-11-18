"""Document metadata (FR-04): PDF metadata, DOI from the first pages, confirmed and enriched by
a DOI lookup. Any lookup failure stores no DOI (D-056). Without a confirmed DOI, a fast-tier LLM
reads page 1 for title, authors, year, and venue (D-068); it never supplies a DOI, and if it
fails the PDF metadata is kept (NFR-04)."""

import html
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import ExternalServiceError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.providers.parser import ParsedDocument, ParsedPage
from app.providers.search import PaperRecord, ScholarlySearchProvider
from app.services.guardrails import clean_untrusted_text, data_block

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"

# Pages searched for the paper's own DOI and title heading; later pages hold the references.
DOI_PAGES = 2
_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_TRAILING = ".,;:'\"]}"
# UTF-8 read as Latin-1/CP1252 ("â€™"), replacement characters, and stray control characters.
_MOJIBAKE = re.compile(r"â€|Ã.|Â|�|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Glyphs some PDF producers map to the Braille block (e.g. "⠜Plasmonic Nanomaterials⠀").
_JUNK_GLYPHS = re.compile(r"[⠀-⣿]")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HEADING_MARKUP = re.compile(r"[*_`]")
_SPACES = re.compile(r"\s+")
_AUTHOR_SEPARATORS = re.compile(r"\s*(?:;|,|\band\b|&)\s*")

MetadataSource = Literal["pdf", "llm", "crossref", "openalex", "fake"]
_LOOKUP_SOURCES: dict[str, MetadataSource] = {
    "crossref": "crossref",
    "openalex": "openalex",
    "fake": "fake",
}


class DocumentMetadata(BaseModel):
    """What ingestion stores on the document record."""

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    # Only a DOI that Crossref or OpenAlex confirmed (D-056).
    doi: str | None = None
    source: MetadataSource = "pdf"


class FirstPageMetadata(BaseModel):
    """What the LLM read on page 1; empty where the page does not say. There is no DOI field:
    only a DOI the lookup confirmed is stored (D-056)."""

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=2100)
    venue: str | None = None


class FirstPageExtractor:
    """Reads title, authors, year, and venue from page 1 with one LLM call (FR-04).

    Give it the fast-tier LLM: the input is one page and the output a few fields.
    """

    def __init__(self, llm: LLMProvider, *, max_chars: int) -> None:
        self._llm = llm
        self._max_chars = max_chars

    async def extract(self, document: ParsedDocument) -> FirstPageMetadata | None:
        """The fields on page 1; None if the page has no text or the call fails."""
        if not document.pages:
            return None
        text = clean_untrusted_text(document.pages[0].markdown).strip()[: self._max_chars]
        if not text:
            return None
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("services", "first_page_metadata", PROMPT_VERSION),
            ),
            ChatMessage(role="user", content=data_block("first_page", text)),
        ]
        try:
            result = await self._llm.generate_structured(messages, FirstPageMetadata, temperature=0)
        except ExternalServiceError as error:
            logger.warning("First-page metadata extraction failed: %s", error.message)
            return None
        return result.output


class MetadataService:
    """Builds `DocumentMetadata` from a parsed PDF, a DOI lookup, and page 1 read by an LLM.

    Without `first_page`, documents without a confirmed DOI keep their PDF metadata.
    """

    def __init__(
        self,
        search: ScholarlySearchProvider,
        *,
        max_candidates: int,
        first_page: FirstPageExtractor | None = None,
    ) -> None:
        self._search = search
        self._max_candidates = max_candidates
        self._first_page = first_page

    async def extract(self, document: ParsedDocument) -> DocumentMetadata:
        """Lookup metadata for the first DOI candidate confirmed; otherwise page 1 read by the
        LLM, with the PDF metadata filling its gaps."""
        base = pdf_metadata(document)
        candidates = doi_candidates(document.pages)[: self._max_candidates]
        for doi in candidates:
            try:
                record = await self._search.get_by_doi(doi.value)
            except ExternalServiceError as error:
                # The service is down, so later candidates would fail too. No DOI is stored
                # without confirmation (D-056).
                logger.warning("DOI lookup unavailable, keeping PDF metadata: %s", error.message)
                break
            if record is not None:
                return _merge(base, record, doi.value)
            logger.info("DOI candidate not found: %s", doi.value)
        if self._first_page is None:
            return base
        extracted = await self._first_page.extract(document)
        return base if extracted is None else _merge_first_page(base, extracted)


class DoiCandidate(BaseModel):
    """A DOI found in the text; `at_line_end` candidates are less likely to have run on."""

    value: str
    at_line_end: bool


def doi_candidates(pages: list[ParsedPage]) -> list[DoiCandidate]:
    """DOIs on the first pages, those ending at a line break first, then in page order."""
    found: list[DoiCandidate] = []
    for page in pages[:DOI_PAGES]:
        for line in page.raw_text.splitlines():
            stripped = line.rstrip()
            for match in _DOI.finditer(stripped):
                value = normalize_doi(match.group())
                if value:
                    found.append(
                        DoiCandidate(value=value, at_line_end=match.end() == len(stripped))
                    )
    ordered = [c for c in found if c.at_line_end] + [c for c in found if not c.at_line_end]
    unique: dict[str, DoiCandidate] = {}
    for candidate in ordered:
        unique.setdefault(candidate.value, candidate)
    return list(unique.values())


def normalize_doi(raw: str) -> str | None:
    """Lower-case, without trailing punctuation; a closing parenthesis only if unbalanced."""
    value = raw.strip().lower()
    while value and (value[-1] in _TRAILING or _unbalanced_close(value)):
        value = value[:-1]
    return value if _DOI.fullmatch(value) else None


def _unbalanced_close(value: str) -> bool:
    """A trailing ')' that closes nothing in the DOI, e.g. "(doi: 10.1/x)"."""
    return value.endswith(")") and value.count("(") < value.count(")")


def pdf_metadata(document: ParsedDocument) -> DocumentMetadata:
    """Title and authors from the PDF's own metadata; title falls back to the first heading."""
    title = clean_text(document.metadata.title) or first_heading(document.pages)
    authors = split_authors(clean_text(document.metadata.author))
    return DocumentMetadata(title=title, authors=authors)


def clean_text(value: str | None) -> str | None:
    """The value without junk glyphs, or None if it is empty or garbled (mojibake)."""
    if value is None:
        return None
    value = _SPACES.sub(" ", _JUNK_GLYPHS.sub("", value)).strip()
    if not value or _MOJIBAKE.search(value):
        return None
    return value


def split_authors(value: str | None) -> list[str]:
    """Split an author string on ';', ',', 'and', or '&'.

    Entities are unescaped first, so the ';' in "&amp;" is not taken as a separator.
    """
    if value is None:
        return []
    return [name for name in _AUTHOR_SEPARATORS.split(html.unescape(value)) if name]


def first_heading(pages: list[ParsedPage]) -> str | None:
    """The first top-level heading on the first page (of pages 1-2) that has headings.

    Consecutive heading lines of that level are joined (titles split over lines).
    """
    for page in pages[:DOI_PAGES]:
        heading = _first_top_heading(page.markdown)
        if heading:
            return heading
    return None


def _first_top_heading(markdown: str) -> str | None:
    lines: list[tuple[int, str]] = []  # (heading level or 0 for body text, text)
    for line in markdown.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            text = clean_text(_HEADING_MARKUP.sub("", match.group(2)))
            lines.append((len(match.group(1)), text or ""))
        elif line.strip():
            lines.append((0, ""))  # body text ends a run of heading lines
    levels = [level for level, text in lines if level and text]
    if not levels:
        return None
    top = min(levels)
    parts: list[str] = []
    for level, text in lines:
        if level == top and text:
            parts.append(text)
        elif parts:
            break
    return " ".join(parts)


def _merge(base: DocumentMetadata, record: PaperRecord, doi: str) -> DocumentMetadata:
    """The lookup's fields win; the PDF fills the gaps."""
    return DocumentMetadata(
        title=record.title or base.title,
        authors=record.authors or base.authors,
        year=record.year or base.year,
        venue=record.venue or base.venue,
        doi=(record.doi or doi).lower(),
        source=_LOOKUP_SOURCES.get(record.source, "pdf"),
    )


def _merge_first_page(base: DocumentMetadata, extracted: FirstPageMetadata) -> DocumentMetadata:
    """The LLM's fields win (PDF metadata is often a file name or empty); the PDF fills gaps."""
    title = clean_text(extracted.title)
    authors = [name for name in map(clean_text, extracted.authors) if name]
    venue = clean_text(extracted.venue)
    if not (title or authors or extracted.year or venue):
        return base
    return DocumentMetadata(
        title=title or base.title,
        authors=authors or base.authors,
        year=extracted.year or base.year,
        venue=venue or base.venue,
        source="llm",
    )
