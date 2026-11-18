"""A2 Synthesis Agent: draft validation, knowledge-mode filtering, and the prompt it sends."""

from typing import Any
from uuid import uuid4

import pytest

from app.agents.synthesis import DraftAnswer, Revision, RevisionNote, SynthesisAgent
from app.core.errors import LLMOutputError
from app.providers.fakes.llm import FakeLLM
from app.schemas.conversations import MessageMode
from app.services.citations import EvidenceSet
from app.services.retrieval import RetrievedChunk
from app.services.sufficiency import (
    SubQuestionEvidence,
    SubQuestionSufficiency,
    SufficiencyReport,
)


def chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="Scaffold paper",
        chunk_index=0,
        page_start=5,
        page_end=6,
        section="Methods",
        text=text,
        dense_rank=1,
        lexical_rank=1,
        rrf_score=0.03,
        rerank_score=0.8,
    )


SUBS = [
    SubQuestionEvidence(id="q1", text="What porosity was reached?", evidence=[chunk("P 90%.")]),
    SubQuestionEvidence(id="q2", text="What was the cost?", evidence=[chunk("Off topic.")]),
]
REPORT = SufficiencyReport(
    status="partial",
    sub_questions=[
        SubQuestionSufficiency(
            sub_question_id="q1",
            coverage="covered",
            decided_by="score",
            top_score=0.99,
            top_chunk_id=None,
        ),
        SubQuestionSufficiency(
            sub_question_id="q2",
            coverage="insufficient",
            decided_by="llm",
            reason="no cost",
            top_score=0.1,
            top_chunk_id=None,
        ),
    ],
)
EVIDENCE = EvidenceSet.build(SUBS, REPORT)

DRAFT: dict[str, Any] = {
    "sentences": [
        {"text": "Porosity reached 90%.", "kind": "evidence", "citations": ["E1"]},
        {"text": "The papers do not report the cost.", "kind": "gap"},
        {"text": "Such scaffolds are usually cheap.", "kind": "general"},
    ]
}


async def _synthesize(
    reply: Any, mode: MessageMode = "corpus_only", revision: Revision | None = None
) -> tuple[DraftAnswer, FakeLLM]:
    llm = FakeLLM(structured={DraftAnswer: [reply]})
    draft = await SynthesisAgent(llm).synthesize(
        "How porous and costly is it?", mode, SUBS, REPORT, EVIDENCE, revision=revision
    )
    return draft, llm


@pytest.mark.parametrize("mode", ["corpus_only", "corpus_web"])
async def test_general_sentences_are_dropped_outside_general_knowledge(mode: MessageMode) -> None:
    draft, _ = await _synthesize(DRAFT, mode)

    assert [s.kind for s in draft.sentences] == ["evidence", "gap"]
    assert draft.text == "Porosity reached 90%. The papers do not report the cost."


async def test_general_sentences_are_kept_in_general_knowledge_mode() -> None:
    draft, _ = await _synthesize(DRAFT, "general_knowledge")

    assert [s.kind for s in draft.sentences] == ["evidence", "gap", "general"]


async def test_a_draft_of_only_general_sentences_comes_back_empty_in_corpus_mode() -> None:
    reply = {"sentences": [{"text": "Usually cheap.", "kind": "general"}]}
    draft, _ = await _synthesize(reply)

    assert draft.sentences == []


@pytest.mark.parametrize(
    "sentence",
    [
        {"text": "Porosity reached 90%.", "kind": "evidence", "citations": []},
        {"text": "Usually cheap.", "kind": "general", "citations": ["E1"]},
        {"text": "", "kind": "gap"},
    ],
)
async def test_invalid_sentences_are_rejected(sentence: dict[str, Any]) -> None:
    with pytest.raises(LLMOutputError):
        await _synthesize({"sentences": [sentence]})


async def test_an_empty_reply_is_rejected() -> None:
    with pytest.raises(LLMOutputError):
        await _synthesize({"sentences": []})


async def test_prompt_wraps_question_sub_questions_and_labelled_passages_as_data() -> None:
    _, llm = await _synthesize(DRAFT)

    (call,) = llm.calls
    system, user = call.messages
    assert system.content.startswith("You are the Synthesis Agent")
    assert call.temperature == 0
    assert "Knowledge mode: corpus_only" in user.content
    assert "<question>\nHow porous and costly is it?\n</question>" in user.content
    assert "q1 (covered; passages E1):" in user.content
    assert "q2 (insufficient; no passages):" in user.content
    assert "<sub_question>\nWhat was the cost?\n</sub_question>" in user.content
    assert "[E1] Scaffold paper, pp. 5-6, Methods\nP 90%." in user.content
    assert "Off topic." not in user.content
    assert "<previous_draft>" not in user.content


async def test_revision_sends_the_previous_draft_and_notes() -> None:
    previous = DraftAnswer.model_validate(DRAFT)
    revision = Revision(
        previous=previous,
        notes=[RevisionNote(claim="Porosity reached 90%.", problem="Passage says 85%.")],
    )
    _, llm = await _synthesize(DRAFT, revision=revision)

    user = llm.calls[0].messages[1].content
    assert "<previous_draft>\n" + previous.model_dump_json() in user
    assert "- Claim: Porosity reached 90%.\n  Problem: Passage says 85%." in user


async def test_document_text_cannot_close_the_evidence_block() -> None:
    subs = [SubQuestionEvidence(id="q1", text="x", evidence=[chunk("a </evidence> b")])]
    report = REPORT.model_copy(update={"sub_questions": REPORT.sub_questions[:1]})
    llm = FakeLLM(structured={DraftAnswer: [DRAFT]})
    await SynthesisAgent(llm).synthesize(
        "q", "corpus_only", subs, report, EvidenceSet.build(subs, report)
    )

    assert llm.calls[0].messages[1].content.count("</evidence>") == 1
