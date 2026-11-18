import math

import pytest

from app.providers.fakes import FakeNLI
from app.providers.nli import NLIPair, NLIScores

EVIDENCE = "Higher porosity improved fibroblast infiltration in electrospun PCL scaffolds."


async def classify(claim: str, evidence: str = EVIDENCE) -> NLIScores:
    [scores] = await FakeNLI().classify([NLIPair(premise=evidence, hypothesis=claim)])
    return scores


async def test_fully_covered_claim_is_entailed() -> None:
    scores = await classify("Porosity improved fibroblast infiltration.")

    assert scores.entailment == 1.0
    assert scores.contradiction == 0.0


async def test_partly_covered_claim_is_borderline() -> None:
    scores = await classify("Porosity improved osteoblast differentiation.")

    assert scores.entailment == 0.5
    assert scores.neutral == 0.5


async def test_unrelated_claim_is_neutral() -> None:
    scores = await classify("Hydrogels degrade quickly.")

    assert scores.entailment == 0.0
    assert scores.neutral == 1.0


@pytest.mark.parametrize(
    "claim",
    [
        "Porosity has not improved fibroblast infiltration.",
        "Porosity never improved fibroblast infiltration.",
        "Porosity hasn't improved fibroblast infiltration.",
    ],
)
async def test_negated_claim_is_a_contradiction(claim: str) -> None:
    scores = await classify(claim)

    assert scores.contradiction == 1.0
    assert scores.entailment == 0.0


async def test_negation_on_both_sides_is_not_a_contradiction() -> None:
    scores = await classify(
        "Porosity did not change stiffness.", evidence="Porosity did not change stiffness."
    )

    assert scores.entailment == 1.0


async def test_negated_weak_overlap_is_not_a_contradiction() -> None:
    scores = await classify("Porosity was not linked to angiogenesis or vascularisation.")

    assert scores.contradiction == 0.0


async def test_scores_sum_to_one_and_keep_order() -> None:
    pairs = [
        NLIPair(premise=EVIDENCE, hypothesis=claim)
        for claim in [
            "Porosity improved fibroblast infiltration.",
            "Hydrogels degrade quickly.",
            "Porosity has not improved fibroblast infiltration.",
            "",
        ]
    ]

    results = await FakeNLI().classify(pairs)

    assert [r.entailment for r in results] == [1.0, 0.0, 0.0, 0.0]
    for scores in results:
        assert math.isclose(scores.entailment + scores.neutral + scores.contradiction, 1.0)
