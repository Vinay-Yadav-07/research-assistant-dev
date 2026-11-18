"""QA graph and runner (SRS §5.4, §7.1–§7.3) with fake providers and an in-memory checkpointer.

Every path through the graph, through the runner's persistence: what is stored for the run,
the approval, and the answer, and how many LLM calls each path makes. Checkpoints go through
the strict serializer used in production, so a state value it cannot restore fails here.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agents.query_analyzer import QueryPlan, SubQuestion
from app.agents.synthesis import DraftAnswer, DraftSentence
from app.agents.verification import (
    JudgeReport,
    JudgeVerdict,
)
from app.core.errors import (
    ConflictError,
    InvalidInputError,
    LLMProviderError,
    NotFoundError,
)
from app.graphs.qa import EXTERNAL_SEARCH_UNAVAILABLE
from app.graphs.qa_runner import (
    CitationsEvent,
    ClaimsEvent,
    ErrorEvent,
)
from app.services.guardrails import GENERAL_KNOWLEDGE_LABEL, out_of_scope_reply
from app.services.sufficiency import (
    AnswerabilityCheck,
    AnswerabilityJudgment,
)
from tests.unit.graphs.qa_harness import (
    GELATIN,
    OTHER_USER,
    POROSITY,
    QUESTION,
    UNANSWERABLE,
    Harness,
    approval_event,
    ask_unanswerable,
    cited,
    collect,
    done,
    harness,
    llm_calls,
    simple_plan,
    stages,
)
from tests.unit.services.test_retrieval import USER

# --- answered from the corpus ---


async def test_sufficient_evidence_is_answered_verified_and_cited() -> None:
    h = await harness()
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1")]))

    run = await h.runner.start(USER, h.conversation_id, QUESTION)
    events = await collect(run)

    assert stages(events) == [
        "analyzing",
        "retrieving",
        "assessing",
        "writing",
        "verifying",
        "citing",
    ]
    claims_event, citations_event = events[-3], events[-2]
    assert isinstance(claims_event, ClaimsEvent) and isinstance(citations_event, CitationsEvent)
    [claim] = claims_event.claims
    assert (claim.text, claim.status) == (POROSITY, "supported")
    [citation] = claim.citations
    assert (citation.source_type, citation.document_title, citation.page_start) == (
        "workspace",
        "Scaffold paper",
        4,
    )
    assert citation.quote == POROSITY
    assert citations_event.citations == claim.citations
    finished = done(events)
    assert (finished.outcome, finished.message.content, finished.message.mode) == (
        "answered",
        POROSITY,
        "corpus_only",
    )
    # A1 and A2 only: S3 fast-passed and NLI accepted the claim (NFR-13).
    assert llm_calls(h) == ["fast:QueryPlan", "strong:DraftAnswer"]
    stored = h.store.runs[run.run_id]
    assert (stored.status, stored.workflow, stored.llm_calls) == ("completed", "qa", 2)
    assert stored.tokens > 0 and stored.latency_ms is not None
    assert finished.message.run_id == run.run_id


async def test_out_of_scope_question_is_refused_without_retrieval() -> None:
    h = await harness()
    h.fast.script(QueryPlan, QueryPlan(intent="out_of_scope"))

    run = await h.runner.start(USER, h.conversation_id, "Write me a poem about cats.")
    events = await collect(run)

    finished = done(events)
    assert (finished.outcome, finished.message.content) == ("out_of_scope", out_of_scope_reply())
    assert stages(events) == ["analyzing"]
    assert h.retrievals == []
    assert llm_calls(h) == ["fast:QueryPlan"]
    assert h.store.runs[run.run_id].status == "completed"


async def test_question_and_answer_are_stored_in_the_conversation() -> None:
    h = await harness()
    h.fast.script(QueryPlan, QueryPlan(intent="out_of_scope"))

    run = await h.runner.start(USER, h.conversation_id, "  Write me a poem.  ")
    await collect(run)

    question, answer = sorted(h.store.messages.values(), key=lambda m: m.created_at)
    # The question links to its run, so the history can find an unanswered one (SRS §20).
    assert (question.role, question.content) == ("user", "Write me a poem.")
    assert question.run_id == run.run_id
    assert (answer.role, answer.run_id) == ("assistant", run.run_id)


async def test_an_empty_question_is_rejected_before_anything_is_stored() -> None:
    h = await harness()

    with pytest.raises(InvalidInputError):
        await h.runner.start(USER, h.conversation_id, "   ")

    assert h.store.messages == {} and h.store.runs == {}


async def test_another_users_conversation_is_not_found() -> None:
    h = await harness()

    with pytest.raises(NotFoundError):
        await h.runner.start(OTHER_USER, h.conversation_id, QUESTION)

    assert h.store.runs == {}


# --- retrieval waves and named papers ---


async def test_dependent_sub_questions_are_retrieved_in_a_later_wave() -> None:
    h = await harness(corpus=(POROSITY, GELATIN))
    plan = QueryPlan(
        intent="multi_hop",
        sub_questions=[
            SubQuestion(id="q1", text="sintered scaffold porosity"),
            SubQuestion(id="q2", text="gelatin coating degraded", depends_on=["q1"]),
            SubQuestion(id="q3", text="porosity ninety percent"),
        ],
    )
    h.fast.script(QueryPlan, plan)
    h.strong.script(
        DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1"), cited(GELATIN, "E2")])
    )

    events = await collect(await h.runner.start(USER, h.conversation_id, "Porosity and gelatin?"))

    assert done(events).outcome == "answered"
    first_wave = {query for query, _ in h.retrievals[:2]}
    assert first_wave == {"sintered scaffold porosity", "porosity ninety percent"}
    assert h.retrievals[2][0] == "gelatin coating degraded"
    assert llm_calls(h) == ["fast:QueryPlan", "strong:DraftAnswer"]


async def test_named_papers_filter_retrieval_and_unknown_names_do_not() -> None:
    h = await harness(corpus=())
    named = uuid4()
    await h.chunks.add(POROSITY, document_id=named, title="Sintering of bioceramic scaffolds")
    await h.chunks.add(GELATIN, title="Gelatin coatings")
    plan = QueryPlan(
        intent="comparison",
        sub_questions=[
            SubQuestion(
                id="q1", text="sintered scaffold porosity", paper_refs=["bioceramic scaffolds"]
            ),
            SubQuestion(id="q2", text="gelatin coating degraded", paper_refs=["Smith et al."]),
        ],
    )
    h.fast.script(QueryPlan, plan)
    h.strong.script(
        DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1"), cited(GELATIN, "E2")])
    )

    events = await collect(await h.runner.start(USER, h.conversation_id, "Compare the papers."))

    assert done(events).outcome == "answered"
    assert dict(h.retrievals) == {
        "sintered scaffold porosity": [named],
        "gelatin coating degraded": None,
    }


# --- approval gate (S4) ---


async def test_insufficient_evidence_pauses_for_approval() -> None:
    h = await harness(corpus=())

    run, events = await ask_unanswerable(h)

    event = approval_event(events)
    assert event.run_id == run.run_id
    assert event.request.options == ["corpus_only", "corpus_web", "general_knowledge"]
    assert UNANSWERABLE in event.request.reason
    assert stages(events) == ["analyzing", "retrieving", "assessing"]
    stored = h.store.runs[run.run_id]
    assert (stored.status, stored.llm_calls) == ("interrupted", 1)
    [approval] = h.store.approvals
    assert (approval.run_id, approval.decision, approval.reason) == (
        run.run_id,
        None,
        event.request.reason,
    )


async def test_staying_corpus_only_abstains_without_another_llm_call() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)

    events = await collect(await h.runner.resume(USER, run.run_id, "corpus_only"))

    finished = done(events)
    assert finished.outcome == "abstained"
    assert finished.message.content.startswith("I could not find enough evidence")
    assert UNANSWERABLE in finished.message.content
    assert (finished.message.mode, finished.message.run_id) == ("corpus_only", run.run_id)
    assert llm_calls(h) == ["fast:QueryPlan"]
    stored = h.store.runs[run.run_id]
    assert (stored.status, stored.llm_calls) == ("completed", 1)
    assert h.store.approvals[0].decision == "corpus_only"


async def test_partial_coverage_staying_corpus_only_answers_what_is_covered() -> None:
    h = await harness(corpus=(POROSITY,))
    h.fast.script(
        QueryPlan,
        QueryPlan(
            intent="multi_hop",
            sub_questions=[
                SubQuestion(id="q1", text="sintered scaffold porosity"),
                SubQuestion(id="q2", text="bioreactor cost"),
            ],
        ),
    )
    h.strong.script(
        AnswerabilityCheck,
        AnswerabilityCheck(
            judgments=[
                AnswerabilityJudgment(
                    sub_question_id="q2", verdict="insufficient", reason="No costs."
                )
            ]
        ),
    )
    h.strong.script(
        DraftAnswer,
        DraftAnswer(
            sentences=[
                cited(POROSITY, "E1"),
                DraftSentence(text="The papers do not report costs.", kind="gap"),
            ]
        ),
    )
    run = await h.runner.start(USER, h.conversation_id, "Porosity and cost?")
    paused = approval_event(await collect(run))
    assert [s.coverage for s in paused.request.sub_questions] == ["covered", "insufficient"]

    events = await collect(await h.runner.resume(USER, run.run_id, "corpus_only"))

    finished = done(events)
    assert finished.outcome == "answered"
    assert finished.message.content == f"{POROSITY} The papers do not report costs."
    claims = events[-3]
    assert isinstance(claims, ClaimsEvent)
    assert [c.status for c in claims.claims] == ["supported"]
    assert h.store.runs[run.run_id].llm_calls == 3


async def test_general_knowledge_answer_is_labelled_and_never_supported() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)
    h.strong.script(
        DraftAnswer,
        DraftAnswer(sentences=[DraftSentence(text="Bioreactors cost thousands.", kind="general")]),
    )

    events = await collect(await h.runner.resume(USER, run.run_id, "general_knowledge"))

    finished = done(events)
    assert (finished.outcome, finished.message.mode) == ("answered", "general_knowledge")
    claims = events[-3]
    assert isinstance(claims, ClaimsEvent)
    [claim] = claims.claims
    assert claim.status == "uncertain"
    [citation] = claim.citations
    assert (citation.source_type, citation.quote, citation.chunk_id) == (
        "general",
        GENERAL_KNOWLEDGE_LABEL,
        None,
    )
    synthesis_prompt = h.strong.calls[-1].messages[-1].content
    assert "Knowledge mode: general_knowledge" in synthesis_prompt


async def test_external_research_is_a_stub_until_phase_5() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)

    events = await collect(await h.runner.resume(USER, run.run_id, "corpus_web"))

    finished = done(events)
    assert (finished.outcome, finished.message.mode) == ("abstained", "corpus_web")
    assert finished.message.content.endswith(EXTERNAL_SEARCH_UNAVAILABLE)
    assert h.store.approvals[0].decision == "corpus_web"


async def test_corpus_web_conversation_skips_the_prompt() -> None:
    h = await harness(mode="corpus_web", corpus=())

    run, events = await ask_unanswerable(h)

    finished = done(events)
    assert (finished.outcome, finished.message.mode) == ("abstained", "corpus_web")
    assert EXTERNAL_SEARCH_UNAVAILABLE in finished.message.content
    assert h.store.approvals == []
    assert h.store.runs[run.run_id].status == "completed"


async def test_resume_checks_ownership_state_and_options() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)

    with pytest.raises(NotFoundError):
        await h.runner.resume(OTHER_USER, run.run_id, "corpus_only")
    with pytest.raises(InvalidInputError):
        await h.runner.resume(USER, run.run_id, "web_only")
    await collect(await h.runner.resume(USER, run.run_id, "corpus_only"))
    with pytest.raises(ConflictError):
        await h.runner.resume(USER, run.run_id, "general_knowledge")


# --- verification loop (A3) ---


async def test_unsupported_claims_are_revised_at_most_twice_then_removed() -> None:
    h = await harness()
    h.fast.script(QueryPlan, simple_plan())
    wrong = cited("Cells migrated into hollow channels.", "E1")
    h.strong.script(DraftAnswer, *[DraftAnswer(sentences=[wrong])] * 3)
    h.strong.script(
        JudgeReport,
        *[
            JudgeReport(
                verdicts=[JudgeVerdict(claim_id="C1", status="unsupported", problem="Not stated.")]
            )
        ]
        * 3,
    )

    run = await h.runner.start(USER, h.conversation_id, QUESTION)
    events = await collect(run)

    assert done(events).outcome == "abstained"
    assert llm_calls(h) == ["fast:QueryPlan"] + ["strong:DraftAnswer", "strong:JudgeReport"] * 3
    revision_prompt = h.strong.calls[2].messages[-1].content
    assert "Not stated." in revision_prompt
    assert h.store.runs[run.run_id].llm_calls == 7


async def test_a_revision_that_fixes_the_claim_is_kept() -> None:
    h = await harness()
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(
        DraftAnswer,
        DraftAnswer(sentences=[cited("Cells migrated into hollow channels.", "E1")]),
        DraftAnswer(sentences=[cited(POROSITY, "E1")]),
    )
    h.strong.script(
        JudgeReport,
        JudgeReport(
            verdicts=[JudgeVerdict(claim_id="C1", status="unsupported", problem="Not stated.")]
        ),
    )

    events = await collect(await h.runner.start(USER, h.conversation_id, QUESTION))

    assert done(events).message.content == POROSITY
    assert stages(events)[3:] == ["writing", "verifying", "writing", "verifying", "citing"]


# --- failures ---


async def test_llm_failure_fails_the_run_and_keeps_its_usage() -> None:
    h = await harness()
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(DraftAnswer, LLMProviderError("Gemini is down."))

    run = await h.runner.start(USER, h.conversation_id, QUESTION)
    events = await collect(run)

    error = events[-1]
    assert isinstance(error, ErrorEvent)
    assert (error.run_id, error.code, error.message) == (
        run.run_id,
        "llm_unavailable",
        "Gemini is down.",
    )
    stored = h.store.runs[run.run_id]
    assert (stored.status, stored.error, stored.llm_calls) == (
        "failed",
        "llm_unavailable: Gemini is down.",
        1,
    )
    assert stored.finished_at is not None
    assert [m.role for m in h.store.messages.values()] == ["user"]


async def test_failed_answer_save_marks_the_run_failed_separately() -> None:
    h = await harness()
    h.fast.script(QueryPlan, QueryPlan(intent="out_of_scope"))

    async def broken_save(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database went away")

    h.store.save_answer = broken_save  # type: ignore[method-assign]

    run = await h.runner.start(USER, h.conversation_id, "A poem please.")
    events = await collect(run)

    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.code == "internal_error"
    assert h.store.runs[run.run_id].status == "failed"
    assert h.store.rollbacks >= 1


async def test_sweep_excludes_runs_this_process_is_executing() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)

    assert await h.runner.fail_stale(timedelta(minutes=15)) == 0
    assert h.store.runs[run.run_id].status == "interrupted"
    assert h.store.stale_sweeps == [(timedelta(minutes=15), set())]


# --- checkpoints ---


async def checkpoint_exists(h: Harness, run_id: UUID) -> bool:
    config = {"configurable": {"thread_id": str(run_id)}}
    return await h.checkpointer.aget_tuple(config) is not None  # type: ignore[arg-type]


async def test_only_a_paused_run_keeps_its_checkpoints() -> None:
    h = await harness(corpus=())
    run, _ = await ask_unanswerable(h)
    assert await checkpoint_exists(h, run.run_id)

    await collect(await h.runner.resume(USER, run.run_id, "corpus_only"))

    assert not await checkpoint_exists(h, run.run_id)


async def test_a_failed_run_leaves_no_checkpoints() -> None:
    h = await harness()
    h.fast.script(QueryPlan, LLMProviderError("Groq is down."))

    run = await h.runner.start(USER, h.conversation_id, QUESTION)
    await collect(run)

    assert h.store.runs[run.run_id].status == "failed"
    assert not await checkpoint_exists(h, run.run_id)
