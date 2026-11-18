"""A3 Verification Agent: NLI bands, the batched judge, revision notes, and finalizing."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest

from app.agents.synthesis import DraftAnswer
from app.agents.verification import (
    JudgeReport,
    VerificationAgent,
    VerificationOptions,
    VerificationReport,
    premise_windows,
)
from app.core.config import Settings
from app.core.errors import LLMOutputError
from app.providers.fakes.llm import FakeLLM
from app.providers.fakes.nli import FakeNLI
from app.providers.nli import NLIPair, NLIScores
from app.services.citations import EvidenceSet
from app.services.retrieval import RetrievedChunk

OPTIONS = VerificationOptions(
    supported_score=0.9,
    unsupported_score=0.3,
    contradiction_score=0.5,
    window_words=40,
    min_claims=1,
)

PASSAGES = [
    "Porosity reached 90 percent after sintering. The scaffolds were printed by robocasting.",
    "Porosity never reached 90 percent after sintering.",
    "Gelatin coatings degraded completely within 32 weeks.",
]

SUPPORTED = "Porosity reached 90 percent after sintering."
UNSUPPORTED = "Cells migrated into the hollow channels."
BORDERLINE = "Porosity reached 90 percent in mice."


class SpyNLI(FakeNLI):
    """The fake NLI, recording each call's pairs."""

    def __init__(self) -> None:
        self.calls: list[list[NLIPair]] = []

    async def classify(self, pairs: Sequence[NLIPair]) -> list[NLIScores]:
        self.calls.append(list(pairs))
        return await super().classify(pairs)


def chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="Scaffold paper",
        chunk_index=0,
        page_start=3,
        page_end=3,
        section="Results",
        text=text,
        dense_rank=1,
        lexical_rank=1,
        rrf_score=0.03,
        rerank_score=0.9,
    )


EVIDENCE = EvidenceSet([chunk(text) for text in PASSAGES], {"q1": ["E1", "E2", "E3"]})


def draft(*sentences: tuple[str, str, list[str]]) -> DraftAnswer:
    return DraftAnswer.model_validate(
        {"sentences": [{"text": t, "kind": k, "citations": c} for t, k, c in sentences]}
    )


def judged(*verdicts: tuple[str, str, str | None]) -> dict[str, Any]:
    return {"verdicts": [{"claim_id": i, "status": s, "problem": p} for i, s, p in verdicts]}


async def _verify(
    answer: DraftAnswer, *judge_replies: Any
) -> tuple[VerificationReport, FakeLLM, SpyNLI]:
    llm = FakeLLM(structured={JudgeReport: list(judge_replies)})
    nli = SpyNLI()
    report = await VerificationAgent(nli, llm, OPTIONS).verify(answer, EVIDENCE)
    return report, llm, nli


async def test_clear_nli_scores_decide_without_the_judge() -> None:
    answer = draft((SUPPORTED, "evidence", ["E1"]), (UNSUPPORTED, "evidence", ["E3"]))

    report, llm, nli = await _verify(answer)

    assert llm.calls == []
    assert len(nli.calls) == 1
    supported, unsupported = report.claims
    assert (supported.status, supported.decided_by, supported.problem) == ("supported", "nli", None)
    assert supported.support_score == 1.0
    assert [s.label for s in supported.support] == ["E1"]
    assert (unsupported.status, unsupported.decided_by) == ("unsupported", "nli")
    assert unsupported.support_score == 0.0
    assert unsupported.problem == "Its cited passages do not state this."


async def test_borderline_and_contradicted_claims_share_one_judge_call() -> None:
    answer = draft(
        (BORDERLINE, "evidence", ["E1"]),
        (SUPPORTED, "evidence", ["E1", "E2"]),
        (UNSUPPORTED, "evidence", ["E3"]),
    )
    reply = judged(("C1", "partially_supported", "Not tested in mice."), ("C2", "uncertain", "E2."))

    report, llm, _ = await _verify(answer, reply)

    (call,) = llm.calls
    assert call.temperature == 0
    system, user = call.messages
    assert system.content.startswith("You are the verification judge")
    assert f"C1 (evidence; cites E1):\n<claim>\n{BORDERLINE}\n</claim>" in user.content
    assert f"C2 (evidence; cites E1, E2):\n<claim>\n{SUPPORTED}\n</claim>" in user.content
    assert f"[E1]\n{PASSAGES[0]}" in user.content
    assert f"[E2]\n{PASSAGES[1]}" in user.content
    assert PASSAGES[2] not in user.content
    assert UNSUPPORTED not in user.content
    statuses = [(c.status, c.decided_by, c.problem) for c in report.claims]
    assert statuses == [
        ("partially_supported", "judge", "Not tested in mice."),
        ("uncertain", "judge", "E2."),
        ("unsupported", "nli", "Its cited passages do not state this."),
    ]
    contradicted = report.claims[1]
    assert contradicted.support_score == 1.0
    assert [s.contradiction for s in contradicted.support] == [0.0, 1.0]


async def test_gap_sentences_are_judged_only_when_they_cite_passages() -> None:
    answer = draft(
        ("The papers do not report the cost.", "gap", []),
        ("Only porosity is reported, not the cost.", "gap", ["E1"]),
    )

    report, llm, nli = await _verify(answer, judged(("C1", "supported", None)))

    assert "C1 (gap; cites E1)" in llm.calls[0].messages[1].content
    assert nli.calls == []
    (claim,) = report.claims
    assert (claim.sentence, claim.status, claim.decided_by) == (1, "supported", "judge")
    assert claim.support == []
    assert claim.support_score is None


async def test_general_sentences_are_never_checked_or_supported() -> None:
    answer = draft(("Such scaffolds are usually cheap.", "general", []))

    report, llm, nli = await _verify(answer)

    assert llm.calls == []
    assert nli.calls == []
    (claim,) = report.claims
    assert (claim.status, claim.decided_by, claim.problem) == ("uncertain", "not_checked", None)


async def test_labels_outside_the_evidence_are_ignored_and_never_support_a_claim() -> None:
    answer = draft((SUPPORTED, "evidence", ["E9"]), (SUPPORTED, "evidence", ["E9", "E1"]))

    report, _, nli = await _verify(answer)

    outside, mixed = report.claims
    assert (outside.status, outside.decided_by) == ("unsupported", "citations")
    assert outside.citations == []
    assert outside.problem == "It cites no passage from the evidence."
    assert (mixed.status, mixed.citations) == ("supported", ["E1"])
    assert {pair.premise for pair in nli.calls[0]} == {PASSAGES[0]}


async def test_long_chunks_are_scored_in_windows_and_the_best_window_counts() -> None:
    filler = "Robocasting needs a paste with suitable rheology. " * 6
    evidence = EvidenceSet([chunk(filler + SUPPORTED)], {"q1": ["E1"]})
    nli = SpyNLI()
    agent = VerificationAgent(nli, FakeLLM(), OPTIONS)

    report = await agent.verify(draft((SUPPORTED, "evidence", ["E1"])), evidence)

    (pairs,) = nli.calls
    assert len(pairs) > 1
    assert all(len(pair.premise.split()) <= OPTIONS.window_words for pair in pairs)
    assert report.claims[0].status == "supported"


@pytest.mark.parametrize(
    "reply",
    [
        judged(("C1", "supported", None)),
        judged(("C1", "supported", None), ("C2", "supported", None), ("C3", "supported", None)),
        judged(("C1", "supported", None), ("C1", "supported", None)),
        judged(("C1", "supported", None), ("C9", "supported", None)),
    ],
)
async def test_the_judge_must_return_one_verdict_per_claim(reply: dict[str, Any]) -> None:
    answer = draft((BORDERLINE, "evidence", ["E1"]), ("Only porosity.", "gap", ["E1"]))

    with pytest.raises(LLMOutputError):
        await _verify(answer, reply)


async def test_a_judge_verdict_other_than_supported_needs_a_problem() -> None:
    with pytest.raises(LLMOutputError):
        await _verify(draft((BORDERLINE, "evidence", ["E1"])), judged(("C1", "unsupported", " ")))


async def test_revision_notes_cover_unsupported_and_partially_supported_claims() -> None:
    answer = draft(
        (SUPPORTED, "evidence", ["E1"]),
        (BORDERLINE, "evidence", ["E1"]),
        (UNSUPPORTED, "evidence", ["E3"]),
    )
    report, _, _ = await _verify(answer, judged(("C1", "partially_supported", "Not in mice.")))

    revision = report.revision(answer)

    assert report.needs_revision
    assert revision is not None
    assert revision.previous == answer
    assert [(n.claim, n.problem) for n in revision.notes] == [
        (BORDERLINE, "Not in mice."),
        (UNSUPPORTED, "Its cited passages do not state this."),
    ]


async def test_no_revision_when_every_claim_holds() -> None:
    answer = draft((SUPPORTED, "evidence", ["E1"]), ("Usually cheap.", "general", []))
    report, _, _ = await _verify(answer)

    assert not report.needs_revision
    assert report.revision(answer) is None


async def test_finalize_drops_unsupported_claims_and_reindexes_the_rest() -> None:
    answer = draft(
        (UNSUPPORTED, "evidence", ["E3"]),
        ("The papers do not report the cost.", "gap", []),
        (SUPPORTED, "evidence", ["E1"]),
    )
    report, _, _ = await _verify(answer)

    final = VerificationAgent(FakeNLI(), FakeLLM(), OPTIONS).finalize(answer, report)

    assert [s.text for s in final.answer.sentences] == [
        "The papers do not report the cost.",
        SUPPORTED,
    ]
    assert [(c.sentence, c.text) for c in final.claims] == [(1, SUPPORTED)]
    assert [c.text for c in final.removed] == [UNSUPPORTED]
    assert not final.abstain


async def test_finalize_abstains_when_too_few_claims_remain() -> None:
    answer = draft(
        (UNSUPPORTED, "evidence", ["E3"]), ("The papers do not report the cost.", "gap", [])
    )
    report, _, _ = await _verify(answer)

    final = VerificationAgent(FakeNLI(), FakeLLM(), OPTIONS).finalize(answer, report)

    assert final.claims == []
    assert final.abstain


async def test_an_empty_draft_abstains() -> None:
    empty = DraftAnswer.model_construct(sentences=[])
    report, _, _ = await _verify(empty)

    assert VerificationAgent(FakeNLI(), FakeLLM(), OPTIONS).finalize(empty, report).abstain


def test_short_text_is_one_window() -> None:
    assert premise_windows("One two three. Four five.", 10) == ["One two three. Four five."]


def test_windows_share_one_sentence_and_respect_the_word_limit() -> None:
    text = "A b c. D e f. G h i. J k l."

    assert premise_windows(text, 6) == ["A b c. D e f.", "D e f. G h i.", "G h i. J k l."]


def test_a_sentence_longer_than_the_limit_is_its_own_window() -> None:
    text = "Short one. " + "word " * 10 + "end. Last bit."

    windows = premise_windows(text, 5)

    assert windows == ["Short one.", "word " * 10 + "end.", "Last bit."]


def test_a_window_never_repeats_only_the_shared_sentence() -> None:
    windows = premise_windows("A b c d. E f g h. I.", 5)

    assert windows == ["A b c d.", "E f g h. I."]


def test_text_without_sentences_is_one_window() -> None:
    assert premise_windows("", 5) == [""]


def test_overlapping_bands_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported score"):
        VerificationOptions(
            supported_score=0.5,
            unsupported_score=0.6,
            contradiction_score=0.5,
            window_words=40,
            min_claims=1,
        )


def test_options_come_from_settings() -> None:
    settings = Settings(verification_supported_score=0.8, verification_window_words=90)

    options = VerificationOptions.from_settings(settings)

    assert (options.supported_score, options.window_words) == (0.8, 90)
    assert options.unsupported_score == settings.verification_unsupported_score
    assert options.min_claims == settings.verification_min_claims
