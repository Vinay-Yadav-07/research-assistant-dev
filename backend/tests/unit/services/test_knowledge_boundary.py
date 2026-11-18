"""S4: the approval request explains the gap, and only approved modes pass the gate."""

from uuid import uuid4

import pytest

from app.core.errors import PermissionDeniedError
from app.services.knowledge_boundary import (
    APPROVAL_OPTIONS,
    approval_request,
    corpus_coverage,
    require_approval,
)
from app.services.retrieval import RetrievedChunk
from app.services.sufficiency import (
    SubQuestionEvidence,
    SubQuestionSufficiency,
    SufficiencyReport,
)


def chunk(title: str | None, page: int, section: str | None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title=title,
        chunk_index=0,
        page_start=page,
        page_end=page,
        section=section,
        text="Text.",
        dense_rank=1,
        lexical_rank=None,
        rrf_score=0.1,
        rerank_score=0.5,
    )


def scenario() -> tuple[list[SubQuestionEvidence], SufficiencyReport]:
    covered = chunk("Hydrogel paper", 3, "Results")
    partial = chunk(None, 5, None)
    subs = [
        SubQuestionEvidence("q1", "What porosity?", [covered]),
        SubQuestionEvidence("q2", "Which cells?", [partial]),
        SubQuestionEvidence("q3", "What cost?", []),
    ]
    report = SufficiencyReport(
        status="partial",
        sub_questions=[
            SubQuestionSufficiency(
                sub_question_id="q1",
                coverage="covered",
                decided_by="score",
                top_score=0.99,
                top_chunk_id=covered.chunk_id,
            ),
            SubQuestionSufficiency(
                sub_question_id="q2",
                coverage="partial",
                decided_by="llm",
                reason="Only one cell type is named.",
                top_score=0.6,
                top_chunk_id=partial.chunk_id,
            ),
            SubQuestionSufficiency(
                sub_question_id="q3",
                coverage="insufficient",
                decided_by="score",
                top_score=None,
                top_chunk_id=None,
            ),
        ],
    )
    return subs, report


def test_request_names_the_uncovered_parts_and_offers_every_option() -> None:
    request = approval_request(*scenario())

    assert request.options == ["corpus_only", "corpus_web", "general_knowledge"]
    assert request.reason == (
        "The papers in this workspace do not fully answer 2 of 3 part(s) of the question: "
        "Which cells? (only partly covered); What cost? (not covered)."
    )
    assert [s.coverage for s in request.sub_questions] == ["covered", "partial", "insufficient"]
    assert request.sub_questions[1].reason == "Only one cell type is named."


def test_coverage_says_where_the_closest_passage_is() -> None:
    q1, q2, q3 = corpus_coverage(*scenario())

    assert q1.closest is not None and q1.closest.describe() == "Hydrogel paper (p. 3, Results)"
    assert q2.closest is not None and q2.closest.describe() == "Untitled document (p. 5)"
    assert q3.closest is None


def test_a_sufficient_run_needs_no_request() -> None:
    subs, report = scenario()

    with pytest.raises(ValueError, match="no approval"):
        approval_request(subs, report.model_copy(update={"status": "sufficient"}))


def test_corpus_only_never_needs_approval() -> None:
    require_approval("corpus_only", [])


@pytest.mark.parametrize("mode", ["corpus_web", "general_knowledge"])
def test_boundary_crossing_modes_need_a_recorded_approval(mode: str) -> None:
    with pytest.raises(PermissionDeniedError):
        require_approval(mode, [])  # type: ignore[arg-type]
    with pytest.raises(PermissionDeniedError):
        require_approval(mode, [m for m in APPROVAL_OPTIONS if m != mode])  # type: ignore[arg-type]

    require_approval(mode, [mode])  # type: ignore[arg-type]
