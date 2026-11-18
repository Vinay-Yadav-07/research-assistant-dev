"""Builds a QA runner over fake providers, an in-memory store, and an in-memory checkpointer.

Shared by the graph tests and the chat API tests.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.query_analyzer import QueryAnalyzer, QueryPlan
from app.agents.synthesis import DraftSentence, SynthesisAgent
from app.agents.verification import (
    VerificationAgent,
    VerificationOptions,
)
from app.graphs.qa import QAContext, build_qa_graph
from app.graphs.qa_runner import (
    ApprovalRequiredEvent,
    DoneEvent,
    QAEvent,
    QARun,
    QARunner,
    StatusEvent,
)
from app.models.workspace import Workspace
from app.providers.fakes import FakeReranker
from app.providers.fakes.llm import FakeLLM
from app.providers.fakes.nli import FakeNLI
from app.repositories.checkpoints import strict_serializer
from app.services.citations import CitationService
from app.services.conversations import ConversationService
from app.services.retrieval import RetrievalService
from app.services.sufficiency import (
    SufficiencyGate,
    SufficiencyOptions,
)
from tests.unit.conversation_fakes import InMemoryConversationStore
from tests.unit.services.test_retrieval import (
    EMBEDDER,
    USER,
    WORKSPACE,
    InMemoryChunkStore,
    options,
)

OTHER_USER = uuid4()
POROSITY = "Sintered scaffolds reached a porosity of ninety percent."
GELATIN = "Gelatin coatings degraded completely within thirty two weeks."
# Both cover every term of their passage, so S3 fast-passes them with the fake reranker.
QUESTION = "What porosity was reached by sintered scaffolds?"
UNANSWERABLE = "How much does a bioreactor cost?"


@dataclass
class Harness:
    runner: QARunner
    store: InMemoryConversationStore
    chunks: InMemoryChunkStore
    fast: FakeLLM
    strong: FakeLLM
    conversation_id: UUID
    checkpointer: BaseCheckpointSaver[Any]
    retrievals: list[tuple[str, list[UUID] | None]] = field(default_factory=list)


class RecordingRetrieval(RetrievalService):
    """The real S2 over the in-memory store, recording each query and document filter."""

    def __init__(self, harness_log: list[tuple[str, list[UUID] | None]], store: Any) -> None:
        super().__init__(store, embedder=EMBEDDER, reranker=FakeReranker(), options=options())
        self._log = harness_log

    async def retrieve(  # type: ignore[override]
        self, user_id: UUID, workspace_id: UUID, query: str, **kwargs: Any
    ) -> Any:
        ids = kwargs.get("document_ids")
        self._log.append((query, None if ids is None else list(ids)))
        return await super().retrieve(user_id, workspace_id, query, **kwargs)


async def harness(
    *,
    mode: str = "corpus_only",
    corpus: Sequence[str] = (POROSITY,),
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Harness:
    store = InMemoryConversationStore()
    store.workspaces[WORKSPACE] = Workspace(
        id=WORKSPACE, user_id=USER, name="W", default_mode="corpus_only"
    )
    conversation = await store.create(USER, WORKSPACE, title=None, mode=mode)
    chunks = InMemoryChunkStore()
    for text in corpus:
        await chunks.add(text, title="Scaffold paper", page=4)
    fast, strong = FakeLLM(model_name="fast"), FakeLLM(model_name="strong")
    retrievals: list[tuple[str, list[UUID] | None]] = []

    @asynccontextmanager
    async def open_retrieval() -> AsyncIterator[RetrievalService]:
        yield RecordingRetrieval(retrievals, chunks)

    @asynccontextmanager
    async def open_conversations() -> AsyncIterator[ConversationService]:
        yield ConversationService(store)

    context = QAContext(
        open_retrieval=open_retrieval,
        analyzer=QueryAnalyzer(fast),
        gate=SufficiencyGate(strong, SufficiencyOptions(fast_pass_score=0.85, check_chunks=8)),
        synthesis=SynthesisAgent(strong),
        verifier=VerificationAgent(
            FakeNLI(),
            strong,
            VerificationOptions(
                supported_score=0.9,
                unsupported_score=0.0,
                contradiction_score=0.5,
                window_words=120,
                min_claims=1,
            ),
        ),
        citations=CitationService(300),
        max_revisions=2,
    )
    saver = checkpointer or InMemorySaver(serde=strict_serializer())
    runner = QARunner(build_qa_graph(saver), context, open_conversations, max_question_chars=1000)
    return Harness(runner, store, chunks, fast, strong, conversation.id, saver, retrievals)


def simple_plan() -> QueryPlan:
    return QueryPlan(intent="simple_qa")


def cited(text: str, *labels: str) -> DraftSentence:
    return DraftSentence(text=text, kind="evidence", citations=list(labels))


async def collect(run: QARun) -> list[QAEvent]:
    return [event async for event in run.events()]


def stages(events: Sequence[QAEvent]) -> list[str]:
    return [e.stage for e in events if isinstance(e, StatusEvent)]


def done(events: Sequence[QAEvent]) -> DoneEvent:
    assert isinstance(events[-1], DoneEvent), events[-1]
    return events[-1]


def approval_event(events: Sequence[QAEvent]) -> ApprovalRequiredEvent:
    assert isinstance(events[-1], ApprovalRequiredEvent), events[-1]
    return events[-1]


def llm_calls(h: Harness) -> list[str]:
    return [
        f"{llm.model_name}:{call.schema.__name__ if call.schema else 'text'}"
        for llm in (h.fast, h.strong)
        for call in llm.calls
    ]


async def ask_unanswerable(h: Harness) -> tuple[QARun, list[QAEvent]]:
    """A question the corpus cannot answer: no evidence, so S3 needs no LLM call."""
    h.fast.script(QueryPlan, simple_plan())
    run = await h.runner.start(USER, h.conversation_id, UNANSWERABLE)
    return run, await collect(run)
