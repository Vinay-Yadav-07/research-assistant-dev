"""Main question-answering graph (SRS §5.4, §7.1–§7.3): fixed nodes and conditional edges.

A1 plans the question; an out-of-scope plan gets the S6 scoped refusal. S2 retrieves evidence
per sub-question in dependency waves: every sub-question whose dependencies are retrieved runs in
the same wave, in parallel through `Send`. S3 judges coverage. When it is short, S4 pauses the
run with `interrupt()` unless the conversation already approved Corpus + Web; the user's
decision resumes it from the checkpoint. A2 writes the answer, A3 checks it and sends it back
for revision at most `max_revisions` times, and `finalize` drops unsupported claims, maps
citations (S5), and labels general knowledge (S6), or abstains (FR-11).

The state holds only JSON data (ids as strings, Pydantic models dumped), so checkpoints load
with the strict serializer. Agents, services, and the session factory come from the runtime
context, never from the state. Nodes report progress on the custom stream as `{"stage": ...}`.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict, cast
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt

from app.agents.query_analyzer import QueryAnalyzer, QueryPlan, SubQuestion
from app.agents.synthesis import DraftAnswer, SynthesisAgent
from app.agents.verification import ClaimVerdict, VerificationAgent, VerificationReport
from app.core.errors import InvalidInputError
from app.schemas.conversations import MessageMode
from app.services.citations import CitationService, EvidenceSet
from app.services.conversations import AnswerDraft, CitationDraft, ClaimDraft, EvidenceDraft
from app.services.guardrails import GENERAL_KNOWLEDGE_LABEL, abstention_reply, out_of_scope_reply
from app.services.knowledge_boundary import (
    APPROVAL_OPTIONS,
    approval_request,
    corpus_coverage,
    require_approval,
)
from app.services.retrieval import RetrievalService, RetrievedChunk
from app.services.sufficiency import SubQuestionEvidence, SufficiencyGate, SufficiencyReport

logger = logging.getLogger(__name__)

WORKFLOW = "qa"

Stage = Literal["analyzing", "retrieving", "assessing", "writing", "verifying", "citing"]
Outcome = Literal["answered", "abstained", "out_of_scope"]

# Shown with an answer when the user chose external research, which arrives in Phase 5.
EXTERNAL_SEARCH_UNAVAILABLE = (
    "External research search is not available yet, so this answer uses only the papers in "
    "this workspace."
)


@dataclass(frozen=True)
class QAContext:
    """Everything the nodes call; built once at startup and passed to every run."""

    # A retrieval service on a fresh database session, closed when the block ends.
    open_retrieval: Callable[[], AbstractAsyncContextManager[RetrievalService]]
    analyzer: QueryAnalyzer
    gate: SufficiencyGate
    synthesis: SynthesisAgent
    verifier: VerificationAgent
    citations: CitationService
    max_revisions: int


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class QAState(TypedDict, total=False):
    """One run's state; every value is plain JSON."""

    run_id: str
    user_id: str
    workspace_id: str
    question: str
    # Modes this run may use beyond corpus_only: the conversation's corpus_web approval
    # (SRS §10.3) and the decision made at the approval gate.
    approved_modes: list[str]
    # The answer's knowledge mode.
    mode: str
    plan: dict[str, Any]
    # Retrieved chunks per sub-question id, filled by parallel `retrieve` tasks.
    evidence: Annotated[dict[str, list[dict[str, Any]]], _merge]
    sufficiency: dict[str, Any]
    notices: list[str]
    draft: dict[str, Any]
    verification: dict[str, Any]
    revisions: int
    outcome: Outcome
    # The finished `AnswerDraft`.
    answer: dict[str, Any]


class RetrieveTask(TypedDict):
    """The input of one `retrieve` task."""

    user_id: str
    workspace_id: str
    sub_question: dict[str, Any]
    paper_refs: list[str]


def initial_state(
    *,
    run_id: UUID,
    user_id: UUID,
    workspace_id: UUID,
    question: str,
    conversation_mode: str,
) -> QAState:
    """The input of a new run; a corpus_web conversation carries its approval in."""
    return QAState(
        run_id=str(run_id),
        user_id=str(user_id),
        workspace_id=str(workspace_id),
        question=question,
        approved_modes=["corpus_web"] if conversation_mode == "corpus_web" else [],
        mode=conversation_mode,
        evidence={},
        notices=[],
        revisions=0,
    )


# --- nodes ---


async def analyze(state: QAState, runtime: Runtime[QAContext]) -> QAState:
    """A1: intent and sub-questions."""
    runtime.stream_writer({"stage": "analyzing"})
    plan = await runtime.context.analyzer.analyze(state["question"])
    return {"plan": plan.model_dump(mode="json")}


async def retrieve(task: RetrieveTask, runtime: Runtime[QAContext]) -> QAState:
    """S2 for one sub-question, limited to the papers it names when they can be found."""
    runtime.stream_writer({"stage": "retrieving"})
    sub = SubQuestion.model_validate(task["sub_question"])
    user_id, workspace_id = UUID(task["user_id"]), UUID(task["workspace_id"])
    async with runtime.context.open_retrieval() as retrieval:
        papers = await retrieval.resolve_papers(user_id, workspace_id, task["paper_refs"])
        if task["paper_refs"] and not papers:
            logger.info("No workspace document matches the paper references; searching all")
        result = await retrieval.retrieve(
            user_id,
            workspace_id,
            sub.text,
            document_ids=papers or None,
            extra_terms=sub.search_keywords,
        )
    return {"evidence": {sub.id: [c.model_dump(mode="json") for c in result.evidence]}}


async def gather(state: QAState) -> QAState:
    """Join point after a retrieval wave."""
    return {}


async def assess(state: QAState, runtime: Runtime[QAContext]) -> QAState:
    """S3: coverage per sub-question."""
    runtime.stream_writer({"stage": "assessing"})
    report = await runtime.context.gate.assess(_sub_question_evidence(state))
    return {"sufficiency": report.model_dump(mode="json")}


async def approval(state: QAState) -> QAState:
    """S4: pause for the user's decision. Re-runs on resume, so it has no side effects."""
    request = approval_request(_sub_question_evidence(state), _sufficiency(state))
    decision = interrupt(request.model_dump(mode="json"))
    if decision not in APPROVAL_OPTIONS:
        raise InvalidInputError(f"Decision {decision!r} was not offered.")
    approved = list(state["approved_modes"])
    if decision != "corpus_only" and decision not in approved:
        approved.append(decision)
    return {"mode": decision, "approved_modes": approved}


async def external_research(state: QAState) -> QAState:
    """Corpus + Web path: stubbed until Phase 5, so it adds a notice and no evidence."""
    require_approval("corpus_web", state["approved_modes"])
    return {"notices": [*state["notices"], EXTERNAL_SEARCH_UNAVAILABLE]}


async def synthesize(state: QAState, runtime: Runtime[QAContext]) -> QAState:
    """A2: the first draft, or a revision when A3 sent the last one back."""
    runtime.stream_writer({"stage": "writing"})
    mode = cast(MessageMode, state["mode"])
    require_approval(mode, state["approved_modes"])
    revision = None
    revisions = state["revisions"]
    if "verification" in state:
        revision = _verification(state).revision(_draft(state))
        revisions += 1
    subs = _sub_question_evidence(state)
    report = _sufficiency(state)
    draft = await runtime.context.synthesis.synthesize(
        state["question"],
        mode,
        subs,
        report,
        EvidenceSet.build(subs, report),
        revision=revision,
    )
    return {"draft": draft.model_dump(mode="json"), "revisions": revisions}


async def verify(state: QAState, runtime: Runtime[QAContext]) -> QAState:
    """A3: a verdict per claim of the current draft."""
    runtime.stream_writer({"stage": "verifying"})
    report = await runtime.context.verifier.verify(_draft(state), _evidence_set(state))
    return {"verification": report.model_dump(mode="json")}


async def finalize(state: QAState, runtime: Runtime[QAContext]) -> QAState:
    """A3 finalize, S5 citations, S6 labels; abstain when too little survives."""
    runtime.stream_writer({"stage": "citing"})
    verified = runtime.context.verifier.finalize(_draft(state), _verification(state))
    if verified.abstain:
        return _abstention(state)
    evidence = _evidence_set(state)
    claims = [_claim(claim, evidence, runtime.context.citations) for claim in verified.claims]
    content = " ".join([verified.answer.text, *state["notices"]]).strip()
    answer = AnswerDraft(content=content, mode=cast(MessageMode, state["mode"]), claims=claims)
    return {"outcome": "answered", "answer": answer.model_dump(mode="json")}


async def abstain(state: QAState) -> QAState:
    """FR-11: no answer, but what the corpus does and does not cover."""
    return _abstention(state)


async def refuse(state: QAState) -> QAState:
    """S6 scoped refusal for an out-of-scope question."""
    answer = AnswerDraft(content=out_of_scope_reply(), mode=cast(MessageMode, state["mode"]))
    return {"outcome": "out_of_scope", "answer": answer.model_dump(mode="json")}


# --- routing ---


def after_analyze(state: QAState) -> str | list[Send]:
    """Out of scope → refusal; otherwise the first retrieval wave."""
    if _plan(state).intent == "out_of_scope":
        return "refuse"
    return _next_wave(state)


def after_gather(state: QAState) -> str | list[Send]:
    """The next retrieval wave, or S3 once every sub-question has evidence."""
    return _next_wave(state)


def after_assess(state: QAState) -> str:
    """Sufficient → A2; short and Corpus + Web approved → external research; else S4."""
    if _sufficiency(state).status == "sufficient":
        return "synthesize"
    if "corpus_web" in state["approved_modes"]:
        return "external_research"
    return "approval"


def after_approval(state: QAState) -> str:
    """Route by the user's decision."""
    if state["mode"] == "corpus_web":
        return "external_research"
    return _answer_or_abstain(state)


def after_external_research(state: QAState) -> str:
    """No external evidence yet: answer what the corpus covers, or abstain."""
    return _answer_or_abstain(state)


def after_verify(state: QAState, runtime: Runtime[QAContext]) -> str:
    """Back to A2 while claims need revising and revisions remain."""
    if _verification(state).needs_revision and state["revisions"] < runtime.context.max_revisions:
        return "synthesize"
    return "finalize"


def build_qa_graph(
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> CompiledStateGraph[QAState, QAContext, QAState, QAState]:
    """The compiled QA graph; interrupts need a checkpointer."""
    graph = StateGraph(QAState, context_schema=QAContext)
    graph.add_node("analyze", analyze)
    # A `Send` target takes its own input; langgraph 1.2's overloads type-check only nodes
    # whose input is the graph state, with or without `input_schema`.
    graph.add_node("retrieve", retrieve, input_schema=RetrieveTask)  # type: ignore[call-overload]
    graph.add_node("gather", gather)
    graph.add_node("assess", assess)
    graph.add_node("approval", approval)
    graph.add_node("external_research", external_research)
    graph.add_node("synthesize", synthesize)
    graph.add_node("verify", verify)
    graph.add_node("finalize", finalize)
    graph.add_node("abstain", abstain)
    graph.add_node("refuse", refuse)

    graph.add_edge(START, "analyze")
    graph.add_conditional_edges("analyze", after_analyze, ["refuse", "retrieve", "assess"])
    graph.add_edge("retrieve", "gather")
    graph.add_conditional_edges("gather", after_gather, ["retrieve", "assess"])
    graph.add_conditional_edges(
        "assess", after_assess, ["synthesize", "external_research", "approval"]
    )
    graph.add_conditional_edges(
        "approval", after_approval, ["external_research", "synthesize", "abstain"]
    )
    graph.add_conditional_edges(
        "external_research", after_external_research, ["synthesize", "abstain"]
    )
    graph.add_edge("synthesize", "verify")
    graph.add_conditional_edges("verify", after_verify, ["synthesize", "finalize"])
    graph.add_edge("finalize", END)
    graph.add_edge("abstain", END)
    graph.add_edge("refuse", END)
    return graph.compile(checkpointer=checkpointer, name=WORKFLOW)


# --- helpers ---


def _plan(state: QAState) -> QueryPlan:
    return QueryPlan.model_validate(state["plan"])


def _next_wave(state: QAState) -> str | list[Send]:
    plan = _plan(state)
    done = set(state["evidence"])
    wave = [
        sub
        for sub in plan.sub_questions
        if sub.id not in done and all(dep in done for dep in sub.depends_on)
    ]
    if not wave:
        return "assess"
    return [
        Send(
            "retrieve",
            RetrieveTask(
                user_id=state["user_id"],
                workspace_id=state["workspace_id"],
                sub_question=sub.model_dump(mode="json"),
                paper_refs=sub.paper_refs or plan.paper_refs,
            ),
        )
        for sub in wave
    ]


def _answer_or_abstain(state: QAState) -> str:
    """Without any covered evidence, only General Knowledge mode has something to write."""
    if _sufficiency(state).status == "insufficient" and state["mode"] != "general_knowledge":
        return "abstain"
    return "synthesize"


def _sub_question_evidence(state: QAState) -> list[SubQuestionEvidence]:
    return [
        SubQuestionEvidence(
            sub.id,
            sub.text,
            [RetrievedChunk.model_validate(c) for c in state["evidence"].get(sub.id, [])],
        )
        for sub in _plan(state).sub_questions
    ]


def _sufficiency(state: QAState) -> SufficiencyReport:
    return SufficiencyReport.model_validate(state["sufficiency"])


def _evidence_set(state: QAState) -> EvidenceSet:
    return EvidenceSet.build(_sub_question_evidence(state), _sufficiency(state))


def _draft(state: QAState) -> DraftAnswer:
    return DraftAnswer.model_validate(state["draft"])


def _verification(state: QAState) -> VerificationReport:
    return VerificationReport.model_validate(state["verification"])


def _claim(claim: ClaimVerdict, evidence: EvidenceSet, citations: CitationService) -> ClaimDraft:
    """A kept claim with evidence and citations; general knowledge is labelled, never supported."""
    if claim.kind == "general":
        return ClaimDraft(
            text=claim.text,
            status="uncertain",
            citations=[CitationDraft(source_type="general", quote=GENERAL_KNOWLEDGE_LABEL)],
        )
    scores = {support.label: support.entailment for support in claim.support}
    return ClaimDraft(
        text=claim.text,
        status=claim.status,
        support_score=claim.support_score,
        evidence=[
            EvidenceDraft(chunk_id=evidence.chunk(label).chunk_id, score=scores.get(label))
            for label in claim.citations
        ],
        citations=citations.citations_for(claim.text, claim.citations, evidence),
    )


def _abstention(state: QAState) -> QAState:
    coverage = corpus_coverage(_sub_question_evidence(state), _sufficiency(state))
    closest = list(dict.fromkeys(c.closest.describe() for c in coverage if c.closest))
    content = abstention_reply(
        [c.text for c in coverage if c.coverage == "insufficient"], closest, state["notices"]
    )
    answer = AnswerDraft(content=content, mode=cast(MessageMode, state["mode"]))
    return {"outcome": "abstained", "answer": answer.model_dump(mode="json")}


def outcome_of(state: dict[str, Any]) -> tuple[Outcome, AnswerDraft]:
    """The finished run's outcome and answer from its final state."""
    return cast(Outcome, state["outcome"]), AnswerDraft.model_validate(state["answer"])
