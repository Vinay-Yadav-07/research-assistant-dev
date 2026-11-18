"""Calibrate the S3 sufficiency gate (FR-10, D-063, D-065) on the benchmark calibration split.

The run lives in `tests/integration/test_sufficiency_supabase.py` (it needs Supabase dev, the
papers, and GEMINI_API_KEY):
    RECORD_EXPERIMENT=1 uv run pytest -m integration \\
        tests/integration/test_sufficiency_supabase.py -s

Each question is retrieved and gated as one sub-question. The report puts false abstention first
(answerable questions judged insufficient), then unanswerable questions judged covered or partial.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class GateOutcome:
    """The gate's decision for one calibration question."""

    id: str
    question: str
    answerable: bool
    top_score: float | None
    coverage: str
    decided_by: str
    reason: str | None


@dataclass(frozen=True)
class GateSummary:
    """Errors of the gate on the calibration split, false abstention first."""

    answerable: int
    unanswerable: int
    false_insufficient: list[GateOutcome]
    false_covered: list[GateOutcome]
    false_partial: list[GateOutcome]
    llm_checked: int
    # Highest top score among unanswerable questions, and answerable ones at the fast pass.
    max_unanswerable_score: float
    answerable_fast_passed: int


def summarize(outcomes: Sequence[GateOutcome], *, fast_pass_score: float) -> GateSummary:
    """Count the gate's errors on labelled questions."""
    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    if not answerable or not unanswerable:
        raise ValueError("calibration needs answerable and unanswerable questions")
    return GateSummary(
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        false_insufficient=[o for o in answerable if o.coverage == "insufficient"],
        false_covered=[o for o in unanswerable if o.coverage == "covered"],
        false_partial=[o for o in unanswerable if o.coverage == "partial"],
        llm_checked=sum(o.decided_by == "llm" for o in outcomes),
        max_unanswerable_score=max(o.top_score or 0.0 for o in unanswerable),
        answerable_fast_passed=sum((o.top_score or 0.0) >= fast_pass_score for o in answerable),
    )
