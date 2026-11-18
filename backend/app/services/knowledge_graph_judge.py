"""Relationship judge prototype for S10 (D-081 follow-up; not used by graph generation).

One bounded LLM call checks a paper's candidate relationships, labelled `R1`, `R2`, ..., each
with its verbatim quote and the sentence before it, and returns one verdict per candidate:
`stated` (this paper states it), `not_stated` (co-mention, another relationship or direction,
or an inference), or `other_work` (cited studies or background). Only `stated` would be kept.
The quote stays the evidence; the context sentence only helps judge attribution and is passed
explicitly, even when there is none. A missing, contradictory, or unparseable verdict counts as
not stated, so the judge can only remove relationships, never add them.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import LLMOutputError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.services.guardrails import data_block

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
LABEL_PREFIX = "R"
MAX_CANDIDATES_PER_CALL = 20

Verdict = Literal["stated", "not_stated", "other_work"]
Reason = Literal[
    "stated",
    "co_mention",
    "wrong_relation",
    "wrong_direction",
    "inferred",
    "cited_study",
    "background",
]
# Reasons each verdict may give; any other pairing is treated as not stated.
REASONS: dict[str, frozenset[str]] = {
    "stated": frozenset({"stated"}),
    "not_stated": frozenset({"co_mention", "wrong_relation", "wrong_direction", "inferred"}),
    "other_work": frozenset({"cited_study", "background"}),
}
DEFINITIONS: dict[str, str] = {
    "uses": "the source method uses or builds on the target",
    "evaluated_on": "the source method is evaluated, trained, or tested on the target dataset",
    "measured_by": "the source's performance or result is measured with the target metric",
    "addresses": "the source method is applied to or solves the target task",
    "compared_with": "the paper compares the two methods",
    "reports": "the paper reports the target finding about the source",
}


class VerdictDraft(BaseModel):
    """The LLM's verdict on one candidate."""

    candidate: str
    verdict: Verdict
    reason: Reason


class JudgeReply(BaseModel):
    """The LLM's verdicts for one call."""

    verdicts: list[VerdictDraft] = Field(default_factory=list)


@dataclass(frozen=True)
class JudgeCandidate:
    """One relationship to judge, with its verbatim quote and the sentence before it."""

    id: str
    relation_type: str
    source_name: str
    source_type: str
    target_name: str
    target_type: str
    quote: str
    context: str
    context_source: Literal["same_passage", "previous_passage", "none"]
    section: str | None = None


@dataclass(frozen=True)
class JudgeOutcome:
    """The judge's decision; `reason` is `no_verdict`, `inconsistent`, or `judge_invalid` when
    the reply could not be used."""

    candidate_id: str
    verdict: Verdict
    reason: str

    @property
    def kept(self) -> bool:
        """Whether the relationship would be kept."""
        return self.verdict == "stated"


class RelationshipJudge:
    """Checks candidate relationships of one paper. Give it the graph-tier LLM or another
    model whose quota is separate from interactive Q&A."""

    def __init__(self, llm: LLMProvider, *, max_output_tokens: int = 1500) -> None:
        self._llm = llm
        self._max_output_tokens = max_output_tokens

    async def judge(
        self, paper_title: str | None, candidates: Sequence[JudgeCandidate]
    ) -> list[JudgeOutcome]:
        """One outcome per candidate, in order. Provider errors (quota, outages) propagate."""
        outcomes: list[JudgeOutcome] = []
        for start in range(0, len(candidates), MAX_CANDIDATES_PER_CALL):
            group = list(candidates[start : start + MAX_CANDIDATES_PER_CALL])
            outcomes += await self._judge_group(paper_title, group)
        return outcomes

    async def _judge_group(
        self, paper_title: str | None, group: Sequence[JudgeCandidate]
    ) -> list[JudgeOutcome]:
        labels = {f"{LABEL_PREFIX}{n}": c for n, c in enumerate(group, start=1)}
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("services", "kg_relationship_judge", PROMPT_VERSION),
            ),
            ChatMessage(role="user", content=judge_request(paper_title, labels)),
        ]
        reply: JudgeReply | None = None
        for attempt in range(2):
            try:
                result = await self._llm.generate_structured(
                    messages, JudgeReply, temperature=0, max_output_tokens=self._max_output_tokens
                )
            except LLMOutputError:
                logger.warning("Relationship judge output invalid (attempt %d)", attempt + 1)
                continue
            reply = result.output
            break
        if reply is None:
            return [JudgeOutcome(c.id, "not_stated", "judge_invalid") for c in group]
        verdicts: dict[str, VerdictDraft] = {}
        for given in reply.verdicts:
            verdicts.setdefault(given.candidate.strip(), given)
        outcomes = []
        for label, candidate in labels.items():
            draft = verdicts.get(label)
            if draft is None:
                outcomes.append(JudgeOutcome(candidate.id, "not_stated", "no_verdict"))
            elif draft.reason not in REASONS[draft.verdict]:
                outcomes.append(JudgeOutcome(candidate.id, "not_stated", "inconsistent"))
            else:
                outcomes.append(JudgeOutcome(candidate.id, draft.verdict, draft.reason))
        return outcomes


def judge_request(paper_title: str | None, labels: dict[str, JudgeCandidate]) -> str:
    """The paper title and each candidate with its quote and context sentence as data."""
    blocks = []
    for label, c in labels.items():
        context = c.context if c.context_source != "none" else "(none: the quote opens the paper)"
        where = {
            "same_passage": "same passage",
            "previous_passage": "end of the previous passage",
            "none": "none",
        }[c.context_source]
        blocks.append(
            f"[{label}] {c.relation_type}: {DEFINITIONS.get(c.relation_type, c.relation_type)}\n"
            f"source ({c.source_type}): {c.source_name}\n"
            f"target ({c.target_type}): {c.target_name}\n"
            + (f"section: {c.section}\n" if c.section else "")
            + f"context sentence ({where}): {context}\n"
            f"quote: {c.quote}"
        )
    return "\n\n".join(
        [
            data_block("paper_title", paper_title or "Untitled"),
            data_block("candidates", "\n\n".join(blocks)),
        ]
    )
