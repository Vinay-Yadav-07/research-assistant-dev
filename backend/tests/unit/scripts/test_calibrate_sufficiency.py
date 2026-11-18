"""S3 calibration summary and the benchmark v1 calibration split (D-063, D-065)."""

import pytest

from scripts.calibrate_sufficiency import GateOutcome, summarize


def outcome(
    id_: str, answerable: bool, coverage: str, score: float, by: str = "llm"
) -> GateOutcome:
    return GateOutcome(id_, "q?", answerable, score, coverage, by, "reason")


def test_summary_puts_each_error_kind_in_its_list() -> None:
    outcomes = [
        outcome("a1", True, "covered", 0.99, "score"),
        outcome("a2", True, "partial", 0.4),
        outcome("a3", True, "insufficient", 0.2),
        outcome("u1", False, "insufficient", 0.3),
        outcome("u2", False, "covered", 0.9),
        outcome("u3", False, "partial", 0.5),
    ]
    summary = summarize(outcomes, fast_pass_score=0.97)

    assert (summary.answerable, summary.unanswerable) == (3, 3)
    assert [o.id for o in summary.false_insufficient] == ["a3"]
    assert [o.id for o in summary.false_covered] == ["u2"]
    assert [o.id for o in summary.false_partial] == ["u3"]
    assert summary.llm_checked == 5
    assert summary.max_unanswerable_score == 0.9
    assert summary.answerable_fast_passed == 1


def test_summary_needs_both_classes() -> None:
    with pytest.raises(ValueError, match="answerable and unanswerable"):
        summarize([outcome("a1", True, "covered", 0.9)], fast_pass_score=0.97)
