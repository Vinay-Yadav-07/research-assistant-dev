"""Section detection and chunking (FR-06, D-044): page-attributed, section-aware chunks."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from app.providers.parser import ParsedPage

TokenCounter = Callable[[str], int]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HEADING_MARKUP = re.compile(r"[*_`]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_SPACES = re.compile(r"\s+")
# Longer "headings" are bold paragraphs the parser promoted; keep them as text.
MAX_HEADING_CHARS = 200


class ChunkDraft(BaseModel):
    """A chunk ready to embed; `page_*` are PDF page indexes, 1-based (D-054)."""

    chunk_index: int = Field(ge=0)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section: str | None
    text: str
    token_count: int = Field(ge=1)
    content_hash: str

    @model_validator(mode="after")
    def _page_range_valid(self) -> "ChunkDraft":
        if self.page_end < self.page_start:
            raise ValueError("page_end must not be before page_start")
        return self


@dataclass(frozen=True)
class _Unit:
    """A sentence (or a piece of an over-long one) with its provenance."""

    text: str
    page: int
    section: str | None
    tokens: int
    starts_paragraph: bool


def chunk_pages(
    pages: list[ParsedPage],
    *,
    count_tokens: TokenCounter,
    min_tokens: int,
    max_tokens: int,
    overlap_ratio: float,
    merge_below_tokens: int,
    hard_max_tokens: int,
) -> list[ChunkDraft]:
    """Split pages into chunks of about `min_tokens`–`max_tokens` tokens.

    Markdown headings set the section, which carries across pages. A chunk never spans two
    sections; within a section, consecutive chunks share about `overlap_ratio` of the target
    size. A chunk under `merge_below_tokens` is merged into the next chunk of its section (or the
    previous one if it is the section's last, or the next is too long), never past
    `hard_max_tokens` (the model's input limit). A section with one short chunk keeps it.
    """
    units = _units(pages, count_tokens, max_tokens)
    overlap_budget = int(overlap_ratio * (min_tokens + max_tokens) / 2)
    groups: list[_Group] = []
    current = _Group([], 0)
    for unit in units:
        if current.units and unit.section != current.section:
            groups.append(current)
            current = _Group([], 0)
        elif current.units and current.tokens + unit.tokens > max_tokens:
            groups.append(current)
            tail = _overlap(current.units, overlap_budget, count_tokens)
            if _total(tail) + unit.tokens > max_tokens:
                tail = []
            current = _Group(tail, len(tail))
        current.units.append(unit)
    if current.units:
        groups.append(current)
    merged = _merge_short(groups, merge_below_tokens, hard_max_tokens)
    return [_draft(index, group.units, count_tokens) for index, group in enumerate(merged)]


@dataclass
class _Group:
    """The units of one chunk; the first `overlap` units repeat the previous chunk's tail."""

    units: list[_Unit]
    overlap: int

    @property
    def tokens(self) -> int:
        return _total(self.units)

    @property
    def section(self) -> str | None:
        return self.units[0].section


def _merge_short(groups: list[_Group], below: int, hard_max: int) -> list[_Group]:
    """Merge each short chunk into a same-section neighbour, dropping the repeated overlap."""
    result = list(groups)
    index = 0
    while index < len(result):
        group = result[index]
        if group.tokens >= below:
            index += 1
            continue
        following = result[index + 1] if index + 1 < len(result) else None
        preceding = result[index - 1] if index > 0 else None
        if following is not None and following.section == group.section:
            candidate = _Group(group.units + following.units[following.overlap :], group.overlap)
            if candidate.tokens <= hard_max:
                result[index : index + 2] = [candidate]
                continue  # the merged chunk may still be short
        # The section's last chunk, or the next one is too long to absorb it.
        if preceding is not None and preceding.section == group.section:
            candidate = _Group(preceding.units + group.units[group.overlap :], preceding.overlap)
            if candidate.tokens <= hard_max:
                result[index - 1 : index + 1] = [candidate]
                index -= 1
                continue
        index += 1
    return result


def _units(pages: list[ParsedPage], count_tokens: TokenCounter, max_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    section: str | None = None
    previous_heading_level: int | None = None
    for page in pages:
        for paragraph in _paragraphs(page.markdown):
            heading = _HEADING.match(paragraph)
            title = _heading_text(heading.group(2)) if heading else ""
            if heading and title and len(title) <= MAX_HEADING_CHARS:
                level = len(heading.group(1))
                # Consecutive same-level headings are one title split over lines.
                if previous_heading_level == level and section:
                    section = f"{section} {title}"
                else:
                    section = title
                previous_heading_level = level
                continue
            previous_heading_level = None
            for index, sentence in enumerate(_sentences(paragraph)):
                for piece, tokens in _fit(sentence, count_tokens, max_tokens):
                    units.append(_Unit(piece, page.page_number, section, tokens, index == 0))
    return units


def _paragraphs(markdown: str) -> list[str]:
    """Blank-line separated blocks; each heading line is its own block."""
    blocks: list[str] = []
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or _HEADING.match(stripped):
            if lines:
                blocks.append(" ".join(lines))
                lines = []
            if stripped:
                blocks.append(stripped)
        else:
            lines.append(stripped)
    if lines:
        blocks.append(" ".join(lines))
    return blocks


def _heading_text(raw: str) -> str:
    return _SPACES.sub(" ", _HEADING_MARKUP.sub("", raw)).strip()


def _sentences(paragraph: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(_SPACES.sub(" ", paragraph).strip()) if part]


def _fit(sentence: str, count_tokens: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    """The sentence, or word windows of it when it alone exceeds `max_tokens`."""
    tokens = count_tokens(sentence)
    if tokens <= max_tokens:
        return [(sentence, tokens)] if tokens > 0 else []
    pieces: list[tuple[str, int]] = []
    words: list[str] = []
    used = 0
    for word in sentence.split(" "):
        word_tokens = count_tokens(word)
        if words and used + word_tokens > max_tokens:
            pieces.append((" ".join(words), used))
            words, used = [], 0
        words.append(word)
        used += word_tokens
    if words:
        pieces.append((" ".join(words), used))
    return pieces


def _total(units: list[_Unit]) -> int:
    return sum(unit.tokens for unit in units)


def _overlap(units: list[_Unit], budget: int, count_tokens: TokenCounter) -> list[_Unit]:
    """Trailing whole sentences within `budget`, or the last sentence's tail words."""
    tail: list[_Unit] = []
    for unit in reversed(units):
        if _total(tail) + unit.tokens > budget:
            break
        tail.insert(0, unit)
    if tail or budget <= 0:
        return tail
    last = units[-1]
    words: list[str] = []
    used = 0
    for word in reversed(last.text.split(" ")):
        word_tokens = count_tokens(word)
        if used + word_tokens > budget:
            break
        words.insert(0, word)
        used += word_tokens
    if not words:
        return []
    return [_Unit(" ".join(words), last.page, last.section, used, False)]


def _draft(index: int, units: list[_Unit], count_tokens: TokenCounter) -> ChunkDraft:
    parts: list[str] = []
    for position, unit in enumerate(units):
        if position > 0:
            parts.append("\n\n" if unit.starts_paragraph else " ")
        parts.append(unit.text)
    text = "".join(parts)
    return ChunkDraft(
        chunk_index=index,
        page_start=min(unit.page for unit in units),
        page_end=max(unit.page for unit in units),
        section=units[0].section,
        text=text,
        token_count=count_tokens(text),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
