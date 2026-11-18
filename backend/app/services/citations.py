"""S5 Citation Service (SRS §5.3, §12.3, FR-13, D-066).

A run's evidence set is the chunks retrieved for the sub-questions S3 judged covered or partial,
deduplicated and labelled `E1`, `E2`, ... in order. A2 cites these short labels instead of chunk
UUIDs; S5 checks that each cited label is in the set and maps it back to its chunk's document,
page range, section, and a quote (the chunk sentence closest to the claim). A label outside the
set is never turned into a citation.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.core.config import Settings
from app.services.conversations import CitationDraft
from app.services.retrieval import RetrievedChunk
from app.services.sufficiency import SubQuestionEvidence, SufficiencyReport

LABEL_PREFIX = "E"

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9]+")
_MIN_WORD_CHARS = 3


@dataclass(frozen=True)
class LabelledChunk:
    """One chunk of the evidence set and the label A2 cites it by."""

    label: str
    chunk: RetrievedChunk


@dataclass(frozen=True)
class LabelCheck:
    """Cited labels split into those in the evidence set and those that are not."""

    valid: list[str]
    invalid: list[str]


class EvidenceSet:
    """The labelled evidence of one run; the only chunks an answer may cite (SRS §12.3)."""

    def __init__(
        self, chunks: Sequence[RetrievedChunk], by_sub_question: dict[str, list[str]]
    ) -> None:
        self._items = [
            LabelledChunk(f"{LABEL_PREFIX}{n}", chunk) for n, chunk in enumerate(chunks, start=1)
        ]
        self._by_label = {item.label: item for item in self._items}
        self._by_sub_question = by_sub_question

    @classmethod
    def build(
        cls, sub_questions: Sequence[SubQuestionEvidence], report: SufficiencyReport
    ) -> "EvidenceSet":
        """Label the evidence of every sub-question S3 did not judge insufficient.

        Chunks keep their retrieval order per sub-question; a chunk retrieved for several
        sub-questions gets one label.
        """
        excluded = set(report.insufficient_ids)
        chunks: list[RetrievedChunk] = []
        labels: dict[str, str] = {}
        by_sub_question: dict[str, list[str]] = {}
        for sub in sub_questions:
            if sub.id in excluded:
                continue
            for chunk in sub.evidence:
                key = str(chunk.chunk_id)
                if key not in labels:
                    chunks.append(chunk)
                    labels[key] = f"{LABEL_PREFIX}{len(chunks)}"
                by_sub_question.setdefault(sub.id, []).append(labels[key])
        return cls(chunks, by_sub_question)

    @property
    def items(self) -> list[LabelledChunk]:
        """Every labelled chunk, in label order."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def labels_for(self, sub_question_id: str) -> list[str]:
        """Labels of the chunks retrieved for one sub-question (empty if it was excluded)."""
        return list(self._by_sub_question.get(sub_question_id, []))

    def chunk(self, label: str) -> RetrievedChunk:
        """The chunk behind a valid label; raises `KeyError` for a label outside the set."""
        return self._by_label[label].chunk

    def check(self, labels: Iterable[str]) -> LabelCheck:
        """Split `labels` (deduplicated, order kept) into valid and invalid ones."""
        unique = list(dict.fromkeys(label.strip() for label in labels))
        return LabelCheck(
            valid=[label for label in unique if label in self._by_label],
            invalid=[label for label in unique if label not in self._by_label],
        )


class CitationService:
    """S5. Turns cited labels into citations with a source snapshot."""

    def __init__(self, quote_max_chars: int) -> None:
        self._quote_max_chars = quote_max_chars

    @classmethod
    def from_settings(cls, settings: Settings) -> "CitationService":
        """Read the quote length from the application settings."""
        return cls(settings.citation_quote_max_chars)

    def citations_for(
        self, claim: str, labels: Iterable[str], evidence: EvidenceSet
    ) -> list[CitationDraft]:
        """Workspace citations for `claim` from the valid `labels`; invalid labels are skipped."""
        citations = []
        for label in evidence.check(labels).valid:
            chunk = evidence.chunk(label)
            citations.append(
                CitationDraft(
                    source_type="workspace",
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    document_title=chunk.document_title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section,
                    quote=self.quote(claim, chunk.text),
                )
            )
        return citations

    def quote(self, claim: str, text: str) -> str:
        """The sentence of `text` sharing the most words with `claim`, cut to the length limit.

        The quote is a verbatim slice of `text`, so the UI can find and highlight it (FR-13).
        Ties go to the earlier sentence.
        """
        sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
        if not sentences:
            return ""
        claim_words = _words(claim)
        best = max(sentences, key=lambda s: len(claim_words & _words(s)))
        return _cut(best, self._quote_max_chars)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= _MIN_WORD_CHARS}


def _cut(text: str, max_chars: int) -> str:
    """`text` cut at the last word boundary within `max_chars` (hard cut if there is none)."""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip()
