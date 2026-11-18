"""A4 comparison, synthesis, contradictions, and gaps: per-paper retrieval, citation checks,
and paper scoping."""

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agents.literature_analysis import (
    ATTRIBUTE_QUERIES,
    NOT_REPORTED,
    ContradictionChecksDraft,
    FindingsDraft,
    GapsDraft,
    LiteratureAnalysisAgent,
    PaperCells,
    SynthesisDraft,
)
from app.core.errors import InvalidInputError, NotFoundError
from app.providers.fakes import FakeReranker
from app.providers.fakes.llm import FakeLLM
from app.providers.fakes.nli import FakeNLI
from app.services.citations import CitationService
from app.services.retrieval import RetrievalService
from tests.unit.services.test_retrieval import (
    EMBEDDER,
    USER,
    WORKSPACE,
    InMemoryChunkStore,
    options,
)

PAPER_A = uuid4()
PAPER_B = uuid4()


async def store_with_papers() -> InMemoryChunkStore:
    store = InMemoryChunkStore()
    await store.add("We aim to grow cartilage on PCL scaffolds.", document_id=PAPER_A, title="A")
    await store.add("Porosity reached 90% after freeze drying.", document_id=PAPER_A, title="A")
    await store.add("Bone cells were seeded on collagen.", document_id=PAPER_B, title="B")
    return store


def agent(
    store: InMemoryChunkStore, llm: FakeLLM, max_papers: int = 5, findings_per_paper: int = 3
) -> LiteratureAnalysisAgent:
    retrieval = RetrievalService(
        store, embedder=EMBEDDER, reranker=FakeReranker(), options=options()
    )
    return LiteratureAnalysisAgent(
        llm,
        retrieval,
        CitationService(300),
        compare_top_k=3,
        compare_max_papers=max_papers,
        synthesis_top_k=3,
        nli=FakeNLI(),
        contradiction_findings_per_paper=findings_per_paper,
        contradiction_nli_score=0.5,
        contradiction_max_pairs=10,
    )


def cells(**values: tuple[str | None, list[str]]) -> dict[str, Any]:
    return {
        "cells": [
            {"attribute": a, "text": text, "citations": labels}
            for a, (text, labels) in values.items()
        ]
    }


async def test_cells_are_cited_or_not_reported() -> None:
    llm = FakeLLM(
        structured={
            PaperCells: [
                cells(
                    objective=("Grow cartilage on PCL scaffolds.", ["E1"]),
                    findings=("Porosity of 90%.", ["E2", "E99"]),
                    materials=("PCL", ["E99"]),  # only an invented label
                    setup=("Uncited claim.", []),
                ),
                cells(materials=("Collagen", ["E1"])),
            ]
        }
    )
    table = await agent(await store_with_papers(), llm).compare(USER, WORKSPACE, [PAPER_A, PAPER_B])

    assert table.attributes == list(ATTRIBUTE_QUERIES)
    assert [p.document_id for p in table.papers] == [PAPER_A, PAPER_B]
    a = {c.attribute: c for c in table.papers[0].cells}
    assert list(a) == list(ATTRIBUTE_QUERIES)
    assert a["objective"].reported and a["objective"].citations[0].document_id == PAPER_A
    assert len(a["findings"].citations) == 1  # E99 dropped
    for name in ("materials", "setup", "methodology", "limitations"):
        assert (a[name].text, a[name].reported, a[name].citations) == (NOT_REPORTED, False, [])
    b = {c.attribute: c for c in table.papers[1].cells}
    assert b["materials"].citations[0].document_id == PAPER_B
    for cell in [*table.papers[0].cells, *table.papers[1].cells]:
        assert cell.citations or cell.text == NOT_REPORTED


async def test_evidence_is_scoped_to_each_paper_and_wrapped_as_data() -> None:
    llm = FakeLLM(structured={PaperCells: [cells(), cells()]})
    await agent(await store_with_papers(), llm).compare(USER, WORKSPACE, [PAPER_A, PAPER_B])

    first, second = (call.messages[-1].content for call in llm.calls)
    assert "<evidence>" in first and "PCL" in first and "collagen" not in first
    assert "collagen" in second and "PCL" not in second


@pytest.mark.parametrize("paper", [uuid4(), None])
async def test_a_paper_outside_the_workspace_is_not_found(paper: UUID | None) -> None:
    store = await store_with_papers()
    other_workspace = uuid4()
    store.workspaces[other_workspace] = USER
    foreign = paper or uuid4()
    if paper is None:  # a ready paper of the user's other workspace
        await store.add("Elsewhere.", workspace_id=other_workspace, document_id=foreign)
    llm = FakeLLM()
    with pytest.raises(NotFoundError):
        await agent(store, llm).compare(USER, WORKSPACE, [PAPER_A, foreign])
    assert llm.calls == []


async def test_another_users_workspace_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await agent(await store_with_papers(), FakeLLM()).compare(
            uuid4(), WORKSPACE, [PAPER_A, PAPER_B]
        )


async def test_too_many_papers_is_invalid() -> None:
    with pytest.raises(InvalidInputError):
        await agent(await store_with_papers(), FakeLLM(), max_papers=2).compare(
            USER, WORKSPACE, [PAPER_A, PAPER_B, uuid4()]
        )


def claim(text: str, papers: list[str], citations: list[str]) -> dict[str, Any]:
    return {"text": text, "papers": papers, "citations": citations}


async def test_synthesis_keeps_only_claims_that_cite_every_named_paper() -> None:
    # Evidence order: E1, E2 from paper A (P1), E3 from paper B (P2).
    themes = [
        {
            "title": "Scaffolds",
            "claims": [
                claim("Both studies used scaffolds.", ["P1", "P2"], ["E1", "E3"]),
                claim("Both studies reached 90% porosity.", ["P1", "P2"], ["E2"]),
                claim("One study froze its scaffolds.", ["P1"], ["E2", "E99"]),
                claim("Unknown paper.", ["P7"], ["E1"]),
                claim("Uncited.", ["P1"], []),
            ],
        },
        {"title": "Empty", "claims": [claim("Invented label.", ["P2"], ["E99"])]},
    ]
    llm = FakeLLM(structured={SynthesisDraft: [{"themes": themes}]})
    result = await agent(await store_with_papers(), llm).synthesize(
        USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B]
    )

    assert result.topic == "scaffolds"
    assert [t.title for t in result.themes] == ["Scaffolds"]
    both, one = result.themes[0].claims
    assert both.document_ids == [PAPER_A, PAPER_B]
    assert {c.document_id for c in both.citations} == {PAPER_A, PAPER_B}
    assert one.document_ids == [PAPER_A] and len(one.citations) == 1


async def test_synthesis_sends_each_papers_evidence_once_as_data() -> None:
    llm = FakeLLM(structured={SynthesisDraft: [{"themes": []}]})
    result = await agent(await store_with_papers(), llm).synthesize(
        USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B]
    )

    assert result.themes == []
    (call,) = llm.calls
    prompt = call.messages[-1].content
    assert "<topic>\nscaffolds\n</topic>" in prompt and "<evidence>" in prompt
    assert "[E1] P1" in prompt and "[E3] P2" in prompt and "[E4]" not in prompt


async def test_synthesis_of_a_paper_outside_the_workspace_is_not_found() -> None:
    llm = FakeLLM()
    with pytest.raises(NotFoundError):
        await agent(await store_with_papers(), llm).synthesize(
            USER, WORKSPACE, "scaffolds", [PAPER_A, uuid4()]
        )
    assert llm.calls == []


async def test_synthesis_of_too_many_papers_is_invalid() -> None:
    with pytest.raises(InvalidInputError):
        await agent(await store_with_papers(), FakeLLM(), max_papers=2).synthesize(
            USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B, uuid4()]
        )


def finding(text: str, paper: str, citations: list[str]) -> dict[str, Any]:
    return {"text": text, "paper": paper, "citations": citations}


# Evidence order as in synthesis: E1, E2 from paper A (P1), E3 from paper B (P2). FakeNLI scores
# a contradiction only between a negated and a non-negated sentence with the same words.
FINDINGS = {
    "findings": [
        finding("Scaffolds improved cell growth.", "P1", ["E1"]),
        finding("Scaffolds did not improve cell growth.", "P1", ["E2"]),
        finding("Scaffolds improved cell growth.", "P2", ["E3"]),
        finding("Collagen was used.", "P1", ["E3"]),  # cites the other paper
        finding("Invented label.", "P2", ["E99"]),
        finding("Unknown paper.", "P7", ["E1"]),
    ]
}


def checks(*items: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "checks": [{"pair": p, "label": label, "context_note": note} for p, label, note in items]
    }


async def test_contradictions_screen_cross_paper_findings_and_keep_labelled_pairs() -> None:
    llm = FakeLLM(
        structured={
            FindingsDraft: [FINDINGS],
            ContradictionChecksDraft: [
                checks(("C1", "context_dependent", " Different cell types. "), ("C7", "none", ""))
            ],
        }
    )
    report = await agent(await store_with_papers(), llm).find_contradictions(
        USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B]
    )

    # Only one pair reaches the check: the two P1 findings are never paired with each other.
    (pair,) = report.contradictions
    assert (pair.finding_a.text, pair.finding_a.document_id) == (
        "Scaffolds did not improve cell growth.",
        PAPER_A,
    )
    assert (pair.finding_b.text, pair.finding_b.document_id) == (
        "Scaffolds improved cell growth.",
        PAPER_B,
    )
    assert (pair.label, pair.context_note) == ("context_dependent", "Different cell types.")
    assert pair.nli_score >= 0.5
    assert pair.finding_b.citations[0].document_id == PAPER_B
    check_prompt = llm.calls[-1].messages[-1].content
    assert "<pairs>" in check_prompt and "[C1]" in check_prompt and "[C2]" not in check_prompt
    assert "<evidence>" in check_prompt

    (record,) = report.records()
    assert record.claim_a == pair.finding_a.text and record.label == "context_dependent"
    assert [r["side"] for r in record.evidence_refs] == ["a", "b"]
    assert record.evidence_refs[1]["document_id"] == str(PAPER_B)


async def test_pairs_the_check_rejects_or_skips_are_dropped() -> None:
    for reply in (checks(("C1", "none", "Agree.")), checks()):
        llm = FakeLLM(structured={FindingsDraft: [FINDINGS], ContradictionChecksDraft: [reply]})
        report = await agent(await store_with_papers(), llm).find_contradictions(
            USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B]
        )
        assert report.contradictions == []


async def test_no_candidate_pair_skips_the_check() -> None:
    # With one finding per paper the contradicting P1 finding is cut; the rest agree.
    llm = FakeLLM(structured={FindingsDraft: [FINDINGS]})
    report = await agent(await store_with_papers(), llm, findings_per_paper=1).find_contradictions(
        USER, WORKSPACE, "scaffolds", [PAPER_A, PAPER_B]
    )

    assert report.contradictions == []
    assert [call.schema for call in llm.calls] == [FindingsDraft]


async def test_contradictions_of_a_paper_outside_the_workspace_are_not_found() -> None:
    llm = FakeLLM()
    with pytest.raises(NotFoundError):
        await agent(await store_with_papers(), llm).find_contradictions(
            USER, WORKSPACE, "scaffolds", [PAPER_A, uuid4()]
        )
    assert llm.calls == []


async def test_gaps_keep_only_those_that_cite_every_named_paper() -> None:
    # Evidence order: E1, E2 from paper A (P1), E3 from paper B (P2).
    gaps = [
        claim("Neither study tested scaffolds in vivo.", ["P1", "P2"], ["E1", "E3"]),
        claim("Both studies lacked long-term data.", ["P1", "P2"], ["E2"]),
        claim("Porosity effects remain untested.", ["P1"], ["E2", "E99"]),
        claim("Uncited.", ["P2"], []),
    ]
    llm = FakeLLM(structured={GapsDraft: [{"gaps": gaps}]})
    report = await agent(await store_with_papers(), llm).find_gaps(
        USER, WORKSPACE, [PAPER_A, PAPER_B]
    )

    both, one = report.gaps
    assert both.document_ids == [PAPER_A, PAPER_B]
    assert one.document_ids == [PAPER_A] and len(one.citations) == 1
    prompt = llm.calls[0].messages[-1].content
    assert "<evidence>" in prompt and "[E1] P1" in prompt and "[E3] P2" in prompt
    first = report.records()[0]
    assert first.description == both.text
    assert {r["document_id"] for r in first.evidence_refs} == {str(PAPER_A), str(PAPER_B)}


async def test_gaps_of_a_paper_outside_the_workspace_are_not_found() -> None:
    llm = FakeLLM()
    with pytest.raises(NotFoundError):
        await agent(await store_with_papers(), llm).find_gaps(USER, WORKSPACE, [PAPER_A, uuid4()])
    assert llm.calls == []


async def test_gaps_of_too_many_papers_are_invalid() -> None:
    with pytest.raises(InvalidInputError):
        await agent(await store_with_papers(), FakeLLM(), max_papers=2).find_gaps(
            USER, WORKSPACE, [PAPER_A, PAPER_B, uuid4()]
        )
