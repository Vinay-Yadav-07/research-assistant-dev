"""S5 citation service (FR-13, D-066): evidence labels, label checks, and citation snapshots."""

from uuid import uuid4

from app.services.citations import CitationService, EvidenceSet
from app.services.retrieval import RetrievedChunk
from app.services.sufficiency import (
    SubQuestionEvidence,
    SubQuestionSufficiency,
    SufficiencyReport,
)


def chunk(text: str = "Some text.", *, page_end: int = 4) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="Scaffold paper",
        chunk_index=0,
        page_start=3,
        page_end=page_end,
        section="Results",
        text=text,
        dense_rank=1,
        lexical_rank=None,
        rrf_score=0.01,
        rerank_score=0.9,
    )


def report(**coverage: str) -> SufficiencyReport:
    return SufficiencyReport.model_validate(
        {
            "status": "partial",
            "sub_questions": [
                SubQuestionSufficiency.model_validate(
                    {
                        "sub_question_id": id_,
                        "coverage": value,
                        "decided_by": "llm",
                        "top_score": None,
                        "top_chunk_id": None,
                    }
                )
                for id_, value in coverage.items()
            ],
        }
    )


def sub(id_: str, *chunks: RetrievedChunk) -> SubQuestionEvidence:
    return SubQuestionEvidence(id=id_, text="a sub-question", evidence=list(chunks))


def test_labels_follow_retrieval_order_and_shared_chunks_get_one_label() -> None:
    a, b, c = chunk(), chunk(), chunk()
    evidence = EvidenceSet.build(
        [sub("q1", a, b), sub("q2", b, c)], report(q1="covered", q2="partial")
    )

    assert [(item.label, item.chunk) for item in evidence.items] == [
        ("E1", a),
        ("E2", b),
        ("E3", c),
    ]
    assert evidence.labels_for("q1") == ["E1", "E2"]
    assert evidence.labels_for("q2") == ["E2", "E3"]


def test_insufficient_sub_questions_add_no_evidence() -> None:
    a, b = chunk(), chunk()
    evidence = EvidenceSet.build(
        [sub("q1", a), sub("q2", b)], report(q1="insufficient", q2="covered")
    )

    assert [item.chunk for item in evidence.items] == [b]
    assert evidence.labels_for("q1") == []
    assert evidence.labels_for("q2") == ["E1"]


def test_check_separates_labels_outside_the_set() -> None:
    evidence = EvidenceSet.build([sub("q1", chunk(), chunk())], report(q1="covered"))

    result = evidence.check(["E2", "E9", " E1 ", "E2", "x"])

    assert result.valid == ["E2", "E1"]
    assert result.invalid == ["E9", "x"]


def test_citations_snapshot_the_source_and_skip_invalid_labels() -> None:
    source = chunk("Pores were 200 µm wide. Porosity reached 90% after freeze-drying.")
    evidence = EvidenceSet.build([sub("q1", source)], report(q1="covered"))

    citations = CitationService(300).citations_for(
        "The scaffold porosity reached 90%.", ["E1", "E7"], evidence
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation.source_type == "workspace"
    assert citation.document_id == source.document_id
    assert citation.chunk_id == source.chunk_id
    assert citation.document_title == "Scaffold paper"
    assert (citation.page_start, citation.page_end) == (3, 4)
    assert citation.section == "Results"
    assert citation.quote == "Porosity reached 90% after freeze-drying."


def test_quote_is_a_verbatim_slice_cut_at_a_word_boundary() -> None:
    text = "Alpha beta gamma delta epsilon. Unrelated sentence here."
    quote = CitationService(20).quote("gamma delta epsilon", text)

    assert quote == "Alpha beta gamma"
    assert quote in text


def test_quote_ties_go_to_the_first_sentence() -> None:
    assert CitationService(300).quote("nothing shared", "First one. Second one.") == "First one."


def test_quote_of_empty_text_is_empty() -> None:
    assert CitationService(300).quote("claim", "   ") == ""
