"""S3 Evidence Sufficiency Gate (SRS §5.3, FR-10, D-065).

A sub-question whose best reranker score (in [0, 1], SRS §8.2) reaches the fast-pass score is
covered without an LLM call. Every other sub-question with evidence goes to one batched LLM
answerability check, which may call it `covered`, `partial`, or `insufficient`; the prompt leans
against false `insufficient` because A3 catches unsupported claims later. Without evidence a
sub-question is insufficient. The run is `sufficient` when every sub-question is covered,
`insufficient` when none has any coverage, and `partial` otherwise; S4 asks for approval in the
last two cases (SRS §7.2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import LLMOutputError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.services.guardrails import data_block
from app.services.retrieval import RetrievedChunk

PROMPT_VERSION = "v1"

Coverage = Literal["covered", "partial", "insufficient"]
SufficiencyStatus = Literal["sufficient", "partial", "insufficient"]


@dataclass(frozen=True)
class SubQuestionEvidence:
    """One sub-question and the evidence retrieved for it."""

    id: str
    text: str
    evidence: Sequence[RetrievedChunk]


@dataclass(frozen=True)
class SufficiencyOptions:
    """The fast-pass score and how many chunks per sub-question the LLM check reads."""

    fast_pass_score: float
    check_chunks: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "SufficiencyOptions":
        """Read the options from the application settings."""
        return cls(
            fast_pass_score=settings.sufficiency_fast_pass_score,
            check_chunks=settings.sufficiency_check_chunks,
        )


class AnswerabilityJudgment(BaseModel):
    """The LLM check's verdict for one sub-question."""

    sub_question_id: str
    verdict: Coverage
    reason: str = Field(min_length=1)


class AnswerabilityCheck(BaseModel):
    """The LLM check's output: one judgment per sub-question it was given."""

    judgments: list[AnswerabilityJudgment]


class SubQuestionSufficiency(BaseModel):
    """The gate's decision for one sub-question."""

    sub_question_id: str
    coverage: Coverage
    decided_by: Literal["score", "llm"]
    # The LLM check's reason; None when the score decided.
    reason: str | None = None
    # Best reranker score; None when retrieval returned nothing.
    top_score: float | None
    # The closest chunk, so S4 can say what the corpus does cover.
    top_chunk_id: UUID | None


class SufficiencyReport(BaseModel):
    """S3's output for one run."""

    status: SufficiencyStatus
    sub_questions: list[SubQuestionSufficiency]

    @property
    def insufficient_ids(self) -> list[str]:
        """Sub-questions without any coverage, in input order."""
        return [s.sub_question_id for s in self.sub_questions if s.coverage == "insufficient"]


class SufficiencyGate:
    """S3. Give it the strong-tier LLM: the check reads several passages per sub-question."""

    def __init__(self, llm: LLMProvider, options: SufficiencyOptions) -> None:
        self._llm = llm
        self._options = options

    async def assess(self, sub_questions: Sequence[SubQuestionEvidence]) -> SufficiencyReport:
        """Decide per sub-question whether its evidence can answer it.

        Raises `ValueError` when there are no sub-questions (out-of-scope questions never reach
        S3), and `LLMOutputError` when the check's judgments do not match the sub-questions.
        """
        if not sub_questions:
            raise ValueError("the sufficiency gate needs at least one sub-question")
        if len({sub.id for sub in sub_questions}) != len(sub_questions):
            raise ValueError("sub-question ids must be unique")
        ranked = {sub.id: _ranked(sub.evidence) for sub in sub_questions}
        to_check = [
            sub
            for sub in sub_questions
            if ranked[sub.id] and _score(ranked[sub.id][0]) < self._options.fast_pass_score
        ]
        judgments = await self._check(to_check, ranked) if to_check else {}

        decisions = []
        for sub in sub_questions:
            chunks = ranked[sub.id]
            top = chunks[0] if chunks else None
            judgment = judgments.get(sub.id)
            decisions.append(
                SubQuestionSufficiency(
                    sub_question_id=sub.id,
                    coverage=judgment.verdict if judgment else "covered" if top else "insufficient",
                    decided_by="llm" if judgment else "score",
                    reason=judgment.reason if judgment else None,
                    top_score=top.rerank_score if top else None,
                    top_chunk_id=top.chunk_id if top else None,
                )
            )
        return SufficiencyReport(status=_status(decisions), sub_questions=decisions)

    async def _check(
        self,
        sub_questions: Sequence[SubQuestionEvidence],
        ranked: dict[str, list[RetrievedChunk]],
    ) -> dict[str, AnswerabilityJudgment]:
        blocks = [
            f"Sub-question {sub.id}:\n"
            + data_block("sub_question", sub.text)
            + "\n"
            + data_block("evidence", _passages(ranked[sub.id][: self._options.check_chunks]))
            for sub in sub_questions
        ]
        messages = [
            ChatMessage(
                role="system", content=load_prompt("services", "sufficiency_check", PROMPT_VERSION)
            ),
            ChatMessage(role="user", content="\n\n".join(blocks)),
        ]
        result = await self._llm.generate_structured(messages, AnswerabilityCheck, temperature=0)
        judgments = {j.sub_question_id: j for j in result.output.judgments}
        expected = {sub.id for sub in sub_questions}
        if set(judgments) != expected or len(result.output.judgments) != len(expected):
            raise LLMOutputError(
                details={
                    "schema": AnswerabilityCheck.__name__,
                    "expected_ids": sorted(expected),
                    "returned_ids": [j.sub_question_id for j in result.output.judgments],
                }
            )
        return judgments


def _ranked(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reranked chunks, best first; chunks without a reranker score are not evidence here."""
    return sorted((c for c in chunks if c.rerank_score is not None), key=lambda c: -_score(c))


def _score(chunk: RetrievedChunk) -> float:
    return chunk.rerank_score or 0.0


def _passages(chunks: Sequence[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{n}] {chunk.document_title or 'Untitled'}, p. {chunk.page_start}"
        + (f", {chunk.section}" if chunk.section else "")
        + f"\n{chunk.text}"
        for n, chunk in enumerate(chunks, start=1)
    )


def _status(decisions: Sequence[SubQuestionSufficiency]) -> SufficiencyStatus:
    if all(d.coverage == "covered" for d in decisions):
        return "sufficient"
    if all(d.coverage == "insufficient" for d in decisions):
        return "insufficient"
    return "partial"
