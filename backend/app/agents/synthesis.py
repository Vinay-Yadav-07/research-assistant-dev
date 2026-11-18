"""A2 Synthesis Agent (SRS §5.2, §7.3, FR-09, FR-11): the answer, written only from evidence.

A2 reads the run's labelled evidence set (S5) and S3's coverage per sub-question. Every factual
sentence cites evidence labels; sub-questions without evidence are answered with `gap`
sentences saying what the corpus does not cover. General-knowledge sentences are kept only when
the user approved General Knowledge mode for this request (SRS §2.3); otherwise they are dropped
here, whatever the model wrote. A3 can send the draft back with revision notes (max 2 loops).
"""

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.schemas.conversations import MessageMode
from app.services.citations import EvidenceSet
from app.services.guardrails import data_block
from app.services.sufficiency import SubQuestionEvidence, SufficiencyReport

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"

SentenceKind = Literal["evidence", "gap", "general"]


class DraftSentence(BaseModel):
    """One sentence of the answer and the evidence labels it cites."""

    text: str = Field(min_length=1)
    # evidence: a factual statement from the passages; gap: what the corpus does not cover;
    # general: general model knowledge (General Knowledge mode only).
    kind: SentenceKind
    citations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_citations(self) -> "DraftSentence":
        if self.kind == "evidence" and not self.citations:
            raise ValueError("an evidence sentence cites at least one passage")
        if self.kind == "general" and self.citations:
            raise ValueError("a general-knowledge sentence cites no passages")
        return self


class DraftAnswer(BaseModel):
    """A2's output: the answer as sentences, in order."""

    sentences: list[DraftSentence] = Field(min_length=1)

    @property
    def text(self) -> str:
        """The answer as plain text, without citation labels."""
        return " ".join(sentence.text for sentence in self.sentences)


class RevisionNote(BaseModel):
    """A claim A3 could not verify and what is wrong with it."""

    claim: str
    problem: str


class Revision(BaseModel):
    """A previous draft and the notes it must be revised by."""

    previous: DraftAnswer
    notes: list[RevisionNote] = Field(min_length=1)


class SynthesisAgent:
    """A2. Give it the strong-tier LLM: it reads and combines every passage of the run."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def synthesize(
        self,
        question: str,
        mode: MessageMode,
        sub_questions: Sequence[SubQuestionEvidence],
        report: SufficiencyReport,
        evidence: EvidenceSet,
        *,
        revision: Revision | None = None,
    ) -> DraftAnswer:
        """Write (or, with `revision`, rewrite) the answer to `question` from `evidence`.

        Outside General Knowledge mode, `general` sentences are dropped, so the draft may come
        back empty; the caller then abstains. Raises `LLMOutputError` if the reply does not
        validate.
        """
        messages = [
            ChatMessage(role="system", content=load_prompt("agents", "synthesis", PROMPT_VERSION)),
            ChatMessage(
                role="user",
                content=_request(question, mode, sub_questions, report, evidence, revision),
            ),
        ]
        result = await self._llm.generate_structured(messages, DraftAnswer, temperature=0)
        return _within_mode(result.output, mode)


def _request(
    question: str,
    mode: MessageMode,
    sub_questions: Sequence[SubQuestionEvidence],
    report: SufficiencyReport,
    evidence: EvidenceSet,
    revision: Revision | None,
) -> str:
    coverage = {s.sub_question_id: s.coverage for s in report.sub_questions}
    lines = [f"Knowledge mode: {mode}", "", data_block("question", question), "", "Sub-questions:"]
    for sub in sub_questions:
        labels = evidence.labels_for(sub.id)
        passages = f"passages {', '.join(labels)}" if labels else "no passages"
        lines.append(f"{sub.id} ({coverage.get(sub.id, 'insufficient')}; {passages}):")
        lines.append(data_block("sub_question", sub.text))
    lines += ["", data_block("evidence", _passages(evidence))]
    if revision is not None:
        notes = "\n".join(f"- Claim: {n.claim}\n  Problem: {n.problem}" for n in revision.notes)
        lines += [
            "",
            "Revise the previous draft according to the revision notes.",
            data_block("previous_draft", revision.previous.model_dump_json()),
            data_block("revision_notes", notes),
        ]
    return "\n".join(lines)


def _passages(evidence: EvidenceSet) -> str:
    if not len(evidence):
        return "(no passages)"
    return "\n\n".join(
        f"[{item.label}] {item.chunk.document_title or 'Untitled'}, "
        + _pages(item.chunk.page_start, item.chunk.page_end)
        + (f", {item.chunk.section}" if item.chunk.section else "")
        + f"\n{item.chunk.text}"
        for item in evidence.items
    )


def _pages(start: int, end: int) -> str:
    return f"p. {start}" if start == end else f"pp. {start}-{end}"


def _within_mode(draft: DraftAnswer, mode: MessageMode) -> DraftAnswer:
    """Drop general-knowledge sentences unless the user approved General Knowledge mode."""
    if mode == "general_knowledge":
        return draft
    kept = [s for s in draft.sentences if s.kind != "general"]
    if len(kept) < len(draft.sentences):
        logger.warning(
            "A2 dropped %d general-knowledge sentence(s) in %s mode",
            len(draft.sentences) - len(kept),
            mode,
        )
    return draft.model_copy(update={"sentences": kept})
