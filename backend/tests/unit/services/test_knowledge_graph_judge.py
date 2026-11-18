"""Relationship judge prototype with scripted replies (no network)."""

from typing import Any

import pytest

from app.core.errors import LLMOutputError, LLMQuotaExceededError
from app.providers.fakes import FakeLLM
from app.services.knowledge_graph_judge import (
    MAX_CANDIDATES_PER_CALL,
    JudgeCandidate,
    JudgeReply,
    RelationshipJudge,
    judge_request,
)


def candidate(n: int, *, context: str = "Wang found that X.", source: str = "same_passage") -> Any:
    return JudgeCandidate(
        id=f"c{n}",
        relation_type="uses",
        source_name="face detection algorithm",
        source_type="method",
        target_name="SSR filter",
        target_type="tool",
        quote="We propose a face detection algorithm using SSR filter.",
        context=context,
        context_source=source,  # type: ignore[arg-type]
        section="Methods",
    )


def verdict(label: str, verdict: str, reason: str) -> dict[str, str]:
    return {"candidate": label, "verdict": verdict, "reason": reason}


async def test_each_candidate_gets_its_verdict_and_only_stated_is_kept() -> None:
    llm = FakeLLM(
        structured={
            JudgeReply: [
                {
                    "verdicts": [
                        verdict("R1", "stated", "stated"),
                        verdict("R2", "other_work", "cited_study"),
                        verdict("R3", "not_stated", "co_mention"),
                    ]
                }
            ]
        }
    )

    outcomes = await RelationshipJudge(llm).judge(
        "Paper", [candidate(1), candidate(2), candidate(3)]
    )

    assert [(o.candidate_id, o.verdict, o.reason, o.kept) for o in outcomes] == [
        ("c1", "stated", "stated", True),
        ("c2", "other_work", "cited_study", False),
        ("c3", "not_stated", "co_mention", False),
    ]
    (call,) = llm.calls
    assert call.temperature == 0


async def test_missing_contradictory_and_unknown_verdicts_are_never_kept() -> None:
    llm = FakeLLM(
        structured={
            JudgeReply: [
                {
                    "verdicts": [
                        verdict("R1", "stated", "cited_study"),
                        verdict("R9", "stated", "stated"),
                        verdict("R2", "not_stated", "inferred"),
                        verdict("R2", "stated", "stated"),
                    ]
                }
            ]
        }
    )

    outcomes = await RelationshipJudge(llm).judge(
        "Paper", [candidate(1), candidate(2), candidate(3)]
    )

    assert [(o.verdict, o.reason) for o in outcomes] == [
        ("not_stated", "inconsistent"),
        ("not_stated", "inferred"),
        ("not_stated", "no_verdict"),
    ]


async def test_an_invalid_reply_is_retried_once_then_drops_the_group() -> None:
    retried = FakeLLM(
        structured={
            JudgeReply: [LLMOutputError(), {"verdicts": [verdict("R1", "stated", "stated")]}]
        }
    )
    failed = FakeLLM(structured={JudgeReply: [LLMOutputError(), LLMOutputError()]})

    assert [o.kept for o in await RelationshipJudge(retried).judge("P", [candidate(1)])] == [True]
    outcomes = await RelationshipJudge(failed).judge("P", [candidate(1), candidate(2)])
    assert [(o.verdict, o.reason) for o in outcomes] == [("not_stated", "judge_invalid")] * 2


async def test_provider_errors_propagate() -> None:
    llm = FakeLLM(structured={JudgeReply: [LLMQuotaExceededError()]})

    with pytest.raises(LLMQuotaExceededError):
        await RelationshipJudge(llm).judge("P", [candidate(1)])


async def test_large_papers_are_judged_in_groups_with_labels_restarting() -> None:
    count = MAX_CANDIDATES_PER_CALL + 2
    first = {"verdicts": [verdict(f"R{n}", "stated", "stated") for n in range(1, 21)]}
    second = {"verdicts": [verdict("R1", "stated", "stated"), verdict("R2", "stated", "stated")]}
    llm = FakeLLM(structured={JudgeReply: [first, second]})

    outcomes = await RelationshipJudge(llm).judge("P", [candidate(n) for n in range(count)])

    assert len(llm.calls) == 2
    assert [o.candidate_id for o in outcomes] == [f"c{n}" for n in range(count)]
    assert all(o.kept for o in outcomes)


def test_the_request_marks_data_and_always_states_the_context() -> None:
    with_context = judge_request("A <paper>", {"R1": candidate(1)})
    without = judge_request(None, {"R1": candidate(1, context="", source="none")})

    assert "<paper_title>\nA <paper>\n</paper_title>" in with_context
    assert "context sentence (same passage): Wang found that X." in with_context
    assert "quote: We propose a face detection algorithm using SSR filter." in with_context
    assert "source (method): face detection algorithm" in with_context
    assert "context sentence (none): (none: the quote opens the paper)" in without
    assert "<paper_title>\nUntitled\n</paper_title>" in without
