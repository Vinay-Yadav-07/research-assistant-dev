"""Sampling of the graph model check (no LLM calls)."""

from app.providers.usage import RunUsage
from scripts.kg_model_check import spent_tokens, spread


def test_spread_samples_evenly_over_the_paper() -> None:
    groups = [[n] for n in range(10)]

    assert spread(groups, 3) == [[0], [3], [6]]  # type: ignore[arg-type]


def test_spread_keeps_short_papers_whole() -> None:
    groups = [[], []]
    assert spread(groups, 5) == groups  # type: ignore[arg-type]


def test_failed_attempts_count_their_worst_case_against_the_token_budget() -> None:
    usage = RunUsage(calls=2, input_tokens=3000, output_tokens=1000, failed_attempts=2)

    assert spent_tokens(usage, failed_attempt_tokens=5000) == 4000 + 2 * 5000
