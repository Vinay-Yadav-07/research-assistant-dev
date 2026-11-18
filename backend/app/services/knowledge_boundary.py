"""S4 Knowledge Boundary & Approval Gate (SRS §5.3, §7.2, §10.3, FR-14).

When S3 finds a sub-question without full coverage, S4 builds the approval request the QA graph
pauses on: why the corpus is insufficient, what it does cover, and the options. The graph
records approved modes in its state; `require_approval` refuses any boundary-crossing mode the
state does not hold, so neither web search nor general knowledge is reached by a prompt alone.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.core.errors import PermissionDeniedError
from app.schemas.conversations import MessageMode
from app.services.sufficiency import Coverage, SubQuestionEvidence, SufficiencyReport

# The choices of SRS §7.2: stay corpus-only, search external research, use general knowledge.
APPROVAL_OPTIONS: tuple[MessageMode, ...] = ("corpus_only", "corpus_web", "general_knowledge")


class ClosestSource(BaseModel):
    """Where the best passage retrieved for a sub-question comes from."""

    document_title: str | None
    page_start: int
    page_end: int
    section: str | None

    def describe(self) -> str:
        """`Title (p. 3, Methods)` for prompts and replies."""
        pages = (
            f"p. {self.page_start}"
            if self.page_start == self.page_end
            else f"pp. {self.page_start}-{self.page_end}"
        )
        where = ", ".join([pages, *([self.section] if self.section else [])])
        return f"{self.document_title or 'Untitled document'} ({where})"


class SubQuestionCoverage(BaseModel):
    """One sub-question, S3's verdict on it, and its closest passage."""

    id: str
    text: str
    coverage: Coverage
    reason: str | None
    closest: ClosestSource | None


class ApprovalRequest(BaseModel):
    """What the user sees when the run pauses (the `approval_required` event)."""

    reason: str
    options: list[MessageMode]
    sub_questions: list[SubQuestionCoverage]


def corpus_coverage(
    sub_questions: Sequence[SubQuestionEvidence], report: SufficiencyReport
) -> list[SubQuestionCoverage]:
    """Each sub-question with S3's coverage and the source of its closest passage."""
    decisions = {d.sub_question_id: d for d in report.sub_questions}
    result = []
    for sub in sub_questions:
        decision = decisions[sub.id]
        top = next((c for c in sub.evidence if c.chunk_id == decision.top_chunk_id), None)
        result.append(
            SubQuestionCoverage(
                id=sub.id,
                text=sub.text,
                coverage=decision.coverage,
                reason=decision.reason,
                closest=None
                if top is None
                else ClosestSource(
                    document_title=top.document_title,
                    page_start=top.page_start,
                    page_end=top.page_end,
                    section=top.section,
                ),
            )
        )
    return result


def approval_request(
    sub_questions: Sequence[SubQuestionEvidence], report: SufficiencyReport
) -> ApprovalRequest:
    """The request for a run whose evidence S3 did not judge sufficient."""
    if report.status == "sufficient":
        raise ValueError("a sufficient run needs no approval")
    coverage = corpus_coverage(sub_questions, report)
    lacking = [c for c in coverage if c.coverage != "covered"]
    parts = "; ".join(
        f"{c.text} ({'only partly covered' if c.coverage == 'partial' else 'not covered'})"
        for c in lacking
    )
    reason = (
        f"The papers in this workspace do not fully answer {len(lacking)} of "
        f"{len(coverage)} part(s) of the question: {parts}."
    )
    return ApprovalRequest(reason=reason, options=list(APPROVAL_OPTIONS), sub_questions=coverage)


def require_approval(mode: MessageMode, approved: Sequence[str]) -> None:
    """Raise unless `mode` is corpus-only or recorded as approved for this run."""
    if mode != "corpus_only" and mode not in approved:
        raise PermissionDeniedError(f"Knowledge mode {mode!r} was not approved for this run.")
