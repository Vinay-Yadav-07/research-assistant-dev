"""NLI comparison metrics and the verifier pairs file (D-067)."""

import pytest

from eval.dataset import load_items
from scripts.compare_nli import Scored, band_outcome, calibrate, load_pairs, roc_auc

ROWS = [
    Scored("supported", 0.98, 0.01),
    Scored("supported", 0.60, 0.02),
    Scored("partial", 0.70, 0.05),
    Scored("unsupported", 0.95, 0.90),
    Scored("unsupported", 0.02, 0.10),
]


def test_band_outcome_counts_each_decision() -> None:
    outcome = band_outcome(ROWS, 0.9, 0.1, 0.5)

    assert outcome["auto_supported"] == 1
    assert outcome["false_supported"] == 0
    assert outcome["false_unsupported"] == 0
    assert outcome["auto_rejected"] == 1
    assert outcome["judged"] == 3
    assert (outcome["supported_total"], outcome["other_total"]) == (2, 3)


def test_a_contradicted_claim_is_never_accepted_without_the_judge() -> None:
    assert band_outcome(ROWS, 0.5, 0.1, 0.95)["false_supported"] == 2
    assert band_outcome(ROWS, 0.5, 0.1, 0.5)["false_supported"] == 1


def test_calibrated_bands_accept_no_other_claim_and_reject_no_supported_one() -> None:
    upper, lower = calibrate(ROWS, 0.5)

    assert (upper, lower) == (0.71, 0.6)
    outcome = band_outcome(ROWS, upper, lower, 0.5)
    assert outcome["false_supported"] == 0
    assert outcome["false_unsupported"] == 0


def test_the_lower_band_never_exceeds_the_upper_one() -> None:
    rows = [Scored("supported", 0.99, 0.0), Scored("partial", 0.5, 0.0)]

    assert calibrate(rows, 0.5) == (0.51, 0.51)


def test_roc_auc_counts_ties_as_half() -> None:
    rows = [Scored("supported", 0.8, 0), Scored("partial", 0.8, 0), Scored("unsupported", 0.1, 0)]

    assert roc_auc(rows) == 0.75


def test_metrics_need_both_classes() -> None:
    with pytest.raises(ValueError):
        roc_auc([Scored("supported", 0.9, 0)])
    with pytest.raises(ValueError):
        calibrate([Scored("partial", 0.9, 0)], 0.5)


def test_verifier_pairs_are_well_formed() -> None:
    pairs = load_pairs()
    answerable = {
        item.id for item in load_items(split="calibration") if item.answerable and item.snippet
    }

    assert len({pair.id for pair in pairs}) == len(pairs)
    assert {pair.item for pair in pairs} == answerable
    for pair in pairs:
        assert pair.split == "calibration"
        assert pair.label in ("supported", "partial", "unsupported")
        assert pair.drafted_by in ("claude", "human")
        assert pair.claim.strip()
    for label in ("supported", "partial", "unsupported"):
        assert sum(pair.label == label for pair in pairs) == len(answerable)


@pytest.mark.parametrize("score", [0.29, 0.57, 0.7, 0.123])
def test_calibrated_bands_survive_float_rounding(score: float) -> None:
    rows = [Scored("supported", score, 0.0), Scored("partial", score, 0.0)]

    upper, lower = calibrate(rows, 0.5)

    assert upper > score
    assert lower <= score
