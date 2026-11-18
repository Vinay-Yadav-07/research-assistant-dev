import math

import pytest

from app.providers.fakes import FakeReranker


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker()


async def test_full_coverage_scores_one_and_no_overlap_scores_zero(
    reranker: FakeReranker,
) -> None:
    scores = await reranker.score(
        "scaffold porosity",
        ["We measured scaffold porosity.", "Hydrogels swell in water."],
    )

    assert math.isclose(scores[0], 1.0)
    assert scores[1] == 0.0


async def test_scores_stay_within_zero_and_one(reranker: FakeReranker) -> None:
    passages = ["", "porosity", "porosity scaffold", "a scaffold of high porosity " * 20]

    scores = await reranker.score("How does scaffold porosity affect infiltration?", passages)

    assert all(0.0 <= score <= 1.0 for score in scores)


async def test_phrase_match_beats_scattered_terms(reranker: FakeReranker) -> None:
    phrase, scattered = await reranker.score(
        "scaffold porosity",
        ["Scaffold porosity was high.", "Porosity was measured on each scaffold."],
    )

    assert phrase > scattered


async def test_repeating_one_term_does_not_inflate_the_score(reranker: FakeReranker) -> None:
    once, repeated, covering = await reranker.score(
        "scaffold porosity",
        [
            "A scaffold design.",
            "Scaffold scaffold scaffold scaffold scaffold design.",
            "Porosity of each scaffold.",
        ],
    )

    assert once == repeated
    assert covering > repeated


async def test_query_without_content_words_scores_zero(reranker: FakeReranker) -> None:
    assert await reranker.score("what is the", ["what is the answer"]) == [0.0]


async def test_output_order_matches_input(reranker: FakeReranker) -> None:
    passages = ["hydrogel", "scaffold porosity", "porosity"]

    scores = await reranker.score("scaffold porosity", passages)

    assert len(scores) == 3
    assert scores[1] > scores[2] > scores[0]
