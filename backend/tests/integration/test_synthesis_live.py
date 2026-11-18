"""A2 + S5 on Supabase dev with the real strong-tier LLM (needs GEMINI_API_KEY).

The first answerable calibration questions of each corpus are retrieved, gated by S3, answered by
A2, and cited by S5 (setup in `live_corpora`). Every evidence sentence must cite only labels from
the run's evidence set, and every answer must cite at least one passage. Prints each answer with
its citations:
`uv run pytest -m integration tests/integration/test_synthesis_live.py -s`
"""

import asyncio
from typing import Any

import pytest

from app.agents.synthesis import SynthesisAgent
from app.services.citations import CitationService, EvidenceSet
from app.services.sufficiency import (
    SubQuestionEvidence,
    SubQuestionSufficiency,
    SufficiencyReport,
)
from eval.dataset import BenchmarkItem
from tests.integration.live_corpora import live_providers, live_settings, run_on_corpora

pytestmark = pytest.mark.integration

# Answerable questions per corpus; kept small for the free-tier daily quota.
QUESTIONS_PER_CORPUS = 3


async def test_answers_cite_only_their_evidence_set() -> None:
    settings = live_settings()
    providers = await asyncio.to_thread(live_providers, settings)
    synthesis = SynthesisAgent(providers.llm_strong)
    citations = CitationService.from_settings(settings)

    async def answer(
        item: BenchmarkItem,
        subs: list[SubQuestionEvidence],
        report: SufficiencyReport,
        evidence: EvidenceSet,
    ) -> Any:
        draft = await synthesis.synthesize(item.question, "corpus_only", subs, report, evidence)
        return item, report.status, evidence, draft

    results = await run_on_corpora(settings, providers, QUESTIONS_PER_CORPUS, answer)

    problems = []
    for item, status, evidence, draft in results:
        print(f"\n{item.id} [{status}] {item.question}  (gold p. {item.page}, {item.paper})")
        cited = 0
        for sentence in draft.sentences:
            check = evidence.check(sentence.citations)
            sources = citations.citations_for(sentence.text, sentence.citations, evidence)
            pages = ", ".join(f"p. {c.page_start}" for c in sources)
            print(f"  ({sentence.kind}) {sentence.text}  {sentence.citations} {pages}")
            if check.invalid:
                problems.append(f"{item.id}: invalid labels {check.invalid}")
            cited += len(sources)
        if status != "insufficient" and not cited:
            problems.append(f"{item.id}: no citations")
    assert results
    assert not problems, problems


async def test_general_knowledge_mode_answers_what_the_papers_do_not_cover() -> None:
    """Regression: after a General Knowledge approval A2 wrote only a `gap` sentence, so the
    run had no claims and abstained (prompt v2, rule 6)."""
    settings = live_settings()
    providers = await asyncio.to_thread(live_providers, settings)
    question = "At what temperature does pure water boil at sea level?"
    sub = SubQuestionEvidence(id="q1", text=question, evidence=[])
    report = SufficiencyReport(
        status="insufficient",
        sub_questions=[
            SubQuestionSufficiency(
                sub_question_id="q1",
                coverage="insufficient",
                decided_by="score",
                top_score=None,
                top_chunk_id=None,
            )
        ],
    )

    draft = await SynthesisAgent(providers.llm_strong).synthesize(
        question, "general_knowledge", [sub], report, EvidenceSet.build([sub], report)
    )

    for sentence in draft.sentences:
        print(f"  ({sentence.kind}) {sentence.text}")
    assert any(s.kind == "general" for s in draft.sentences)
