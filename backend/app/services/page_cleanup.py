"""Removes running headers, footers, and margin text repeated across pages (S1, before chunking)."""

import logging
import math
import re
from collections import Counter

from pydantic import BaseModel

from app.providers.parser import ParsedPage

logger = logging.getLogger(__name__)

_DIGITS = re.compile(r"\d+")
_HEADING = re.compile(r"^#{1,6}\s")
_MARKUP = re.compile(r"^#+\s*|[*_`]")
_SPACES = re.compile(r"\s+")


class CleanedPages(BaseModel):
    """Pages without boilerplate, plus what was removed (normalized line → pages it was on)."""

    pages: list[ParsedPage]
    removed: dict[str, int]


def remove_repeated_lines(
    pages: list[ParsedPage], *, min_pages: int, min_page_fraction: float, max_line_chars: int
) -> CleanedPages:
    """Drop short lines that recur on many pages, e.g. "Author Manuscript", journal headers, or
    page numbers. Digits are ignored when comparing, so "Page 3 of 12" matches "Page 4 of 12";
    headings compare with their digits, so "Section 1" and "Section 2" both stay.

    A line counts as boilerplate when it is on at least `min_pages` pages and at least
    `min_page_fraction` of all pages. Table rows are never removed.
    """
    threshold = max(min_pages, math.ceil(min_page_fraction * len(pages)))
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update(
            {key for line in page.markdown.splitlines() if (key := _key(line, max_line_chars))}
        )
    repeated = {key: count for key, count in counts.items() if count >= threshold}
    for key, count in sorted(repeated.items()):
        logger.debug("Removing boilerplate line on %d/%d pages: %r", count, len(pages), key)
    cleaned = [
        page.model_copy(update={"markdown": _without(page.markdown, repeated, max_line_chars)})
        for page in pages
    ]
    return CleanedPages(pages=cleaned, removed=repeated)


def _key(line: str, max_line_chars: int) -> str | None:
    """Comparison key for a candidate line, or None if the line can never be boilerplate."""
    stripped = line.strip()
    if not stripped or stripped.startswith("|") or len(stripped) > max_line_chars:
        return None
    normalized = _SPACES.sub(" ", _MARKUP.sub("", stripped)).strip().lower()
    if _HEADING.match(stripped):
        return f"heading: {normalized}" if normalized else None
    return _DIGITS.sub("#", normalized) or None


def _without(markdown: str, repeated: dict[str, int], max_line_chars: int) -> str:
    lines = markdown.splitlines()
    kept = [line for line in lines if _key(line, max_line_chars) not in repeated]
    return "\n".join(kept).strip()
