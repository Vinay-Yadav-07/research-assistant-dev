"""A2 → A3 loop on Supabase dev with the real NLI model and strong-tier LLM (needs GEMINI_API_KEY).

The first answerable calibration questions of each corpus are retrieved, gated by S3, answered by
A2, and verified by A3, with up to 2 revision loops as in SRS §7.3 (setup in `live_corpora`).
Every final claim must have a verdict, no kept claim may be unsupported, and answerable questions
must not all abstain. Prints each loop's verdicts and the final answer:
`uv run pytest -m integration tests/integration/test_verification_live.py -s`
"""

import asyncio
import time
from typing import Any

import pytest

from app.agents.synthesis import SynthesisAgent
from app.agents.verification import VerificationAgent, VerificationOptions, VerifiedAnswer
from app.providers.usage import track_usage
from app.services.citations import EvidenceSet
from app.services.sufficiency import SubQuestionEvidence, SufficiencyReport
from eval.dataset import BenchmarkItem
from tests.integration.live_corpora import live_providers, live_settings, run_on_corpora

pytestmark = pytest.mark.integration

# Answerable questions per corpus; kept small for the free-tier daily quota.
QUESTIONS_PER_CORPUS = 3
MAX_REVISIONS = 2


async def test_verified_answers_keep_no_unsupported_claim() -> None:
    settings = live_settings()
    providers = await asyncio.to_thread(live_providers, settings)
    synthesis = SynthesisAgent(providers.llm_strong)
    verification = VerificationAgent(
        providers.nli, providers.llm_strong, VerificationOptions.from_settings(settings)
    )

    async def answer(
        item: BenchmarkItem,
        subs: list[SubQuestionEvidence],
        report: SufficiencyReport,
        evidence: EvidenceSet,
    ) -> tuple[BenchmarkItem, list[str], VerifiedAnswer, float, Any]:
        log: list[str] = []
        started = time.perf_counter()
        with track_usage() as usage:
            draft = await synthesis.synthesize(item.question, "corpus_only", subs, report, evidence)
            for loop in range(MAX_REVISIONS + 1):
                checked = await verification.verify(draft, evidence)
                for claim in checked.claims:
                    log.append(
                        f"  loop {loop} [{claim.status} by {claim.decided_by}, "
                        f"score {claim.support_score}] {claim.text}"
                        + (f"  -- {claim.problem}" if claim.problem else "")
                    )
                revision = checked.revision(draft)
                if revision is None or loop == MAX_REVISIONS:
                    break
                draft = await synthesis.synthesize(
                    item.question, "corpus_only", subs, report, evidence, revision=revision
                )
            final = verification.finalize(draft, checked)
        return item, log, final, time.perf_counter() - started, usage

    results = await run_on_corpora(settings, providers, QUESTIONS_PER_CORPUS, answer)

    problems = []
    for item, log, final, seconds, usage in results:
        print(f"\n{item.id} {item.question}  (gold p. {item.page}, {item.paper})")
        print("\n".join(log))
        print(
            f"  final ({'abstain' if final.abstain else 'answer'}, {seconds:.1f} s after S3, "
            f"{usage.calls} LLM calls): {final.answer.text}"
        )
        for claim in final.claims:
            if claim.status == "unsupported":
                problems.append(f"{item.id}: kept an unsupported claim")
        if len(final.claims) != sum(s.citations != [] for s in final.answer.sentences):
            problems.append(f"{item.id}: a cited sentence has no verdict")
    assert results
    assert not all(final.abstain for _, _, final, _, _ in results)
    assert not problems, problems
