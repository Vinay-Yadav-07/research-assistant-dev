"""A3 Verification Agent (SRS §5.2, §7.3, §12.2, FR-12, D-067).

Each A2 sentence that cites passages is one claim: A2 already writes one or two closely related
facts per sentence, so no extra LLM call splits the draft. An `evidence` claim is scored against
its cited chunks with the NLI model: every cited chunk is cut into short sentence windows (NLI
models trained on sentence pairs score a whole chunk much worse, D-067), and the claim's support
score is its best entailment over all windows. A score at or above the supported score is
`supported` unless a cited chunk contradicts the claim; below the unsupported score (off by
default) it is `unsupported`. Every other claim, and every `gap` sentence that cites
passages, goes to the LLM judge, all in one batched call. A claim whose citations are all
outside the evidence set is unsupported. `general` sentences are never checked against the
corpus and are never marked supported.

Unsupported and partially supported claims go back to A2 as revision notes (max 2 loops, run by
the QA graph); `finalize` then drops the claims that are still unsupported and says whether too
little remains, in which case the run abstains.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.synthesis import DraftAnswer, DraftSentence, Revision, RevisionNote, SentenceKind
from app.core.config import Settings
from app.core.errors import LLMOutputError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.providers.nli import NLIPair, NLIProvider
from app.schemas.conversations import ClaimStatus
from app.services.citations import EvidenceSet
from app.services.guardrails import data_block

PROMPT_VERSION = "v1"

DecidedBy = Literal["nli", "judge", "citations", "not_checked"]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_NOT_IN_EVIDENCE = "It cites no passage from the evidence."
_NOT_STATED = "Its cited passages do not state this."
_REVISE: tuple[ClaimStatus, ...] = ("unsupported", "partially_supported")


@dataclass(frozen=True)
class VerificationOptions:
    """NLI score bands, the window size, and how many claims an answer needs to be kept."""

    # Best entailment at or above this: supported (without the judge).
    supported_score: float
    # Best entailment below this: unsupported (without the judge).
    unsupported_score: float
    # A cited chunk contradicting the claim at or above this sends it to the judge.
    contradiction_score: float
    # Longest NLI premise window, in words.
    window_words: int
    # Fewer remaining claims than this after the last revision: abstain.
    min_claims: int

    def __post_init__(self) -> None:
        if self.unsupported_score > self.supported_score:
            raise ValueError("the unsupported score must not exceed the supported score")

    @classmethod
    def from_settings(cls, settings: Settings) -> "VerificationOptions":
        """Read the options from the application settings."""
        return cls(
            supported_score=settings.verification_supported_score,
            unsupported_score=settings.verification_unsupported_score,
            contradiction_score=settings.verification_contradiction_score,
            window_words=settings.verification_window_words,
            min_claims=settings.verification_min_claims,
        )


class ChunkSupport(BaseModel):
    """NLI scores of one claim against one cited chunk (best window of the chunk)."""

    label: str
    entailment: float
    contradiction: float


class ClaimVerdict(BaseModel):
    """A3's decision for one claim."""

    # Index of the claim's sentence in the draft.
    sentence: int
    text: str
    kind: SentenceKind
    # Cited labels that are in the evidence set.
    citations: list[str]
    status: ClaimStatus
    decided_by: DecidedBy
    # Best entailment over the cited chunks; None when NLI did not run.
    support_score: float | None = None
    support: list[ChunkSupport] = Field(default_factory=list)
    # What is wrong with the claim; None for supported and unchecked claims.
    problem: str | None = None


class VerificationReport(BaseModel):
    """A3's output for one draft: a verdict per claim, in sentence order."""

    claims: list[ClaimVerdict]

    @property
    def needs_revision(self) -> bool:
        """Whether any claim is unsupported or only partially supported."""
        return any(claim.status in _REVISE for claim in self.claims)

    def revision(self, draft: DraftAnswer) -> Revision | None:
        """Revision notes for A2's next loop, or None when nothing needs revising."""
        notes = [
            RevisionNote(claim=claim.text, problem=claim.problem or _NOT_STATED)
            for claim in self.claims
            if claim.status in _REVISE
        ]
        return Revision(previous=draft, notes=notes) if notes else None


class VerifiedAnswer(BaseModel):
    """The answer after the last loop: unsupported claims removed."""

    answer: DraftAnswer
    # Verdicts of the kept claims; `sentence` indexes `answer`.
    claims: list[ClaimVerdict]
    removed: list[ClaimVerdict]
    # Too little is left to answer: the run abstains (SRS §7.3 step 6).
    abstain: bool


class JudgeVerdict(BaseModel):
    """The judge's verdict for one claim."""

    claim_id: str
    status: ClaimStatus
    problem: str | None = None

    @model_validator(mode="after")
    def _check_problem(self) -> "JudgeVerdict":
        if self.status != "supported" and not (self.problem and self.problem.strip()):
            raise ValueError("a claim that is not supported needs a problem")
        return self


class JudgeReport(BaseModel):
    """The judge's output: one verdict per claim it was given."""

    verdicts: list[JudgeVerdict]


class VerificationAgent:
    """A3. Give it the strong-tier LLM for the judge: it reads several passages per claim."""

    def __init__(self, nli: NLIProvider, llm: LLMProvider, options: VerificationOptions) -> None:
        self._nli = nli
        self._llm = llm
        self._options = options

    async def verify(self, draft: DraftAnswer, evidence: EvidenceSet) -> VerificationReport:
        """Check every claim of `draft` against its cited chunks in `evidence`.

        Raises `LLMOutputError` when the judge's verdicts do not match the claims it was given.
        """
        verdicts: dict[int, ClaimVerdict] = {}
        scored: list[tuple[int, list[str]]] = []
        to_judge: list[tuple[int, list[str]]] = []
        for index, sentence in enumerate(draft.sentences):
            valid = evidence.check(sentence.citations).valid
            if sentence.kind == "general":
                verdicts[index] = _verdict(index, draft, valid, "uncertain", "not_checked")
            elif not sentence.citations:
                continue  # a gap sentence that cites nothing makes no claim about the papers
            elif not valid:
                verdicts[index] = _verdict(
                    index, draft, valid, "unsupported", "citations", _NOT_IN_EVIDENCE
                )
            elif sentence.kind == "gap":
                to_judge.append((index, valid))
            else:
                scored.append((index, valid))

        support = await self._support(draft, scored, evidence)
        for index, valid in scored:
            chunks = support[index]
            best = max(chunk.entailment for chunk in chunks)
            contradicted = any(c.contradiction >= self._options.contradiction_score for c in chunks)
            if best >= self._options.supported_score and not contradicted:
                status: ClaimStatus | None = "supported"
            elif best < self._options.unsupported_score:
                status = "unsupported"
            else:
                status = None
            if status is None:
                to_judge.append((index, valid))
                continue
            verdicts[index] = _verdict(
                index,
                draft,
                valid,
                status,
                "nli",
                None if status == "supported" else _NOT_STATED,
                support=chunks,
            )

        judged = await self._judge(draft, sorted(to_judge), evidence) if to_judge else {}
        for index, valid in to_judge:
            verdict = judged[index]
            chunks = support.get(index, [])
            verdicts[index] = _verdict(
                index,
                draft,
                valid,
                verdict.status,
                "judge",
                None if verdict.status == "supported" else verdict.problem,
                support=chunks,
            )
        return VerificationReport(claims=[verdicts[i] for i in sorted(verdicts)])

    def finalize(self, draft: DraftAnswer, report: VerificationReport) -> VerifiedAnswer:
        """Drop the claims that are still unsupported after the last loop (SRS §7.3 step 6)."""
        by_sentence = {claim.sentence: claim for claim in report.claims}
        sentences: list[DraftSentence] = []
        kept: list[ClaimVerdict] = []
        removed: list[ClaimVerdict] = []
        for index, sentence in enumerate(draft.sentences):
            claim = by_sentence.get(index)
            if claim is not None and claim.status == "unsupported":
                removed.append(claim)
                continue
            if claim is not None:
                kept.append(claim.model_copy(update={"sentence": len(sentences)}))
            sentences.append(sentence)
        return VerifiedAnswer(
            answer=draft.model_copy(update={"sentences": sentences}),
            claims=kept,
            removed=removed,
            abstain=len(kept) < self._options.min_claims,
        )

    async def _support(
        self,
        draft: DraftAnswer,
        scored: Sequence[tuple[int, list[str]]],
        evidence: EvidenceSet,
    ) -> dict[int, list[ChunkSupport]]:
        """Score every (window, claim) pair of the draft in one NLI call."""
        pairs: list[NLIPair] = []
        owners: list[tuple[int, str]] = []
        for index, labels in scored:
            claim = draft.sentences[index].text
            for label in labels:
                text = evidence.chunk(label).text
                for window in premise_windows(text, self._options.window_words):
                    pairs.append(NLIPair(premise=window, hypothesis=claim))
                    owners.append((index, label))
        if not pairs:
            return {}
        scores = await self._nli.classify(pairs)
        best: dict[tuple[int, str], ChunkSupport] = {}
        for owner, score in zip(owners, scores, strict=True):
            current = best.get(owner)
            best[owner] = ChunkSupport(
                label=owner[1],
                entailment=max(score.entailment, current.entailment if current else 0.0),
                contradiction=max(score.contradiction, current.contradiction if current else 0.0),
            )
        return {index: [best[(index, label)] for label in labels] for index, labels in scored}

    async def _judge(
        self,
        draft: DraftAnswer,
        claims: Sequence[tuple[int, list[str]]],
        evidence: EvidenceSet,
    ) -> dict[int, JudgeVerdict]:
        ids = {f"C{n}": index for n, (index, _) in enumerate(claims, start=1)}
        cited_labels = {label for _, labels in claims for label in labels}
        cited = [item.label for item in evidence.items if item.label in cited_labels]
        lines = []
        for claim_id, (index, labels) in zip(ids, claims, strict=True):
            sentence = draft.sentences[index]
            lines.append(f"{claim_id} ({sentence.kind}; cites {', '.join(labels)}):")
            lines.append(data_block("claim", sentence.text))
        passages = "\n\n".join(f"[{label}]\n{evidence.chunk(label).text}" for label in cited)
        messages = [
            ChatMessage(
                role="system",
                content=load_prompt("agents", "verification_judge", PROMPT_VERSION),
            ),
            ChatMessage(
                role="user", content="\n".join(lines) + "\n\n" + data_block("evidence", passages)
            ),
        ]
        result = await self._llm.generate_structured(messages, JudgeReport, temperature=0)
        verdicts = {v.claim_id: v for v in result.output.verdicts}
        if set(verdicts) != set(ids) or len(result.output.verdicts) != len(ids):
            raise LLMOutputError(
                details={
                    "schema": JudgeReport.__name__,
                    "expected_ids": list(ids),
                    "returned_ids": [v.claim_id for v in result.output.verdicts],
                }
            )
        return {index: verdicts[claim_id] for claim_id, index in ids.items()}


def premise_windows(text: str, max_words: int) -> list[str]:
    """`text` cut into windows of whole sentences, each at most `max_words` words.

    Consecutive windows share one sentence, so a fact split across two sentences is still seen
    together once. A single sentence longer than `max_words` is a window of its own.
    """
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    if not sentences:
        return [text]
    counts = [len(sentence.split()) for sentence in sentences]
    windows: list[str] = []
    start = fresh = 0
    while fresh < len(sentences):
        end = fresh + 1
        if start < fresh and counts[start] + counts[fresh] > max_words:
            start = fresh  # the shared sentence does not fit with the next one
        words = sum(counts[start:end])
        while end < len(sentences) and words + counts[end] <= max_words:
            words += counts[end]
            end += 1
        windows.append(" ".join(sentences[start:end]))
        start, fresh = end - 1, end
    return windows


def _verdict(
    index: int,
    draft: DraftAnswer,
    valid: list[str],
    status: ClaimStatus,
    decided_by: DecidedBy,
    problem: str | None = None,
    *,
    support: list[ChunkSupport] | None = None,
) -> ClaimVerdict:
    sentence = draft.sentences[index]
    chunks = support or []
    return ClaimVerdict(
        sentence=index,
        text=sentence.text,
        kind=sentence.kind,
        citations=valid,
        status=status,
        decided_by=decided_by,
        support_score=max((c.entailment for c in chunks), default=None),
        support=chunks,
        problem=problem,
    )
