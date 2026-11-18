"""ConversationService: answer saving is all-or-nothing, and drafts become ordered rows."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.models.conversation import Message
from app.services.conversations import (
    AnswerDraft,
    CitationDraft,
    ClaimDraft,
    ConversationService,
    EvidenceDraft,
    RunProgress,
    RunSummary,
)
from tests.unit.conversation_fakes import InMemoryConversationStore

ALICE = uuid4()
BOB = uuid4()


class FailingStore(InMemoryConversationStore):
    """Fails while saving the answer, after the message was already stored."""

    async def save_answer(
        self, user_id: UUID, message: Message, run_id: UUID, run_changes: dict[str, object]
    ) -> Message | None:
        await self.add_message(user_id, message)
        raise RuntimeError("database went away")


async def conversation(store: InMemoryConversationStore) -> tuple[ConversationService, UUID]:
    service = ConversationService(store)
    workspace = store.add_workspace(ALICE)
    store_conversation = await store.create(ALICE, workspace.id, title=None, mode="corpus_only")
    return service, store_conversation.id


def draft() -> AnswerDraft:
    chunk_id, document_id = uuid4(), uuid4()
    return AnswerDraft(
        content="Answer",
        mode="corpus_only",
        claims=[
            ClaimDraft(
                text="first",
                status="supported",
                support_score=0.9,
                evidence=[EvidenceDraft(chunk_id=chunk_id, score=0.9)],
                citations=[
                    CitationDraft(
                        source_type="workspace",
                        document_id=document_id,
                        chunk_id=chunk_id,
                        document_title="Paper",
                        page_start=2,
                        page_end=2,
                        section="Methods",
                        quote="the quoted span",
                    )
                ],
            ),
            ClaimDraft(text="second", status="partially_supported"),
        ],
    )


async def test_save_answer_stores_ordered_claims_and_finishes_the_run() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)
    run_id = await service.start_run(ALICE, conversation_id, workflow="qa")

    saved = await service.save_answer(
        ALICE, conversation_id, run_id, draft(), RunSummary(llm_calls=4)
    )

    message = store.messages[saved.id]
    assert message.role == "assistant"
    assert message.run_id == run_id
    assert [(c.position, c.text) for c in message.claims] == [(0, "first"), (1, "second")]
    [citation] = message.claims[0].citations
    assert (citation.document_title, citation.page_start, citation.quote) == (
        "Paper",
        2,
        "the quoted span",
    )
    assert message.claims[0].evidence[0].score == 0.9
    assert store.runs[run_id].llm_calls == 4
    assert store.runs[run_id].status == "completed"
    assert store.rollbacks == 0


async def test_failure_mid_save_rolls_back_and_never_commits() -> None:
    store = FailingStore()
    service, conversation_id = await conversation(store)
    run_id = await service.start_run(ALICE, conversation_id, workflow="qa")
    commits_before = store.commits

    with pytest.raises(RuntimeError, match="database went away"):
        await service.save_answer(ALICE, conversation_id, run_id, draft(), RunSummary())

    assert store.rollbacks == 1
    assert store.commits == commits_before


@pytest.mark.parametrize("missing", ["run", "conversation", "other-users-run"])
async def test_missing_or_foreign_conversation_or_run_is_404_and_rolled_back(
    missing: str,
) -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)
    run_id = await service.start_run(ALICE, conversation_id, workflow="qa")
    if missing == "run":
        run_id = uuid4()
    elif missing == "conversation":
        conversation_id = uuid4()
    else:
        store.runs[run_id].user_id = BOB
    commits_before = store.commits

    with pytest.raises(NotFoundError):
        await service.save_answer(ALICE, conversation_id, run_id, draft(), RunSummary())

    assert store.rollbacks == 1
    assert store.commits == commits_before


async def test_start_run_on_another_users_conversation_is_404() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)

    with pytest.raises(NotFoundError):
        await service.start_run(BOB, conversation_id, workflow="qa")

    assert store.runs == {}


async def test_user_message_in_another_users_conversation_is_404() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)

    with pytest.raises(NotFoundError):
        await service.add_user_message(BOB, conversation_id, content="hi", mode="corpus_only")

    assert store.messages == {}


# --- run lifecycle (QA graph) ---

OPTIONS = ["corpus_only", "corpus_web", "general_knowledge"]


async def paused_run(store: InMemoryConversationStore) -> tuple[ConversationService, UUID]:
    service, conversation_id = await conversation(store)
    started = await service.begin_run(ALICE, conversation_id, question="Why?", workflow="qa")
    await service.pause_run(
        ALICE,
        started.run_id,
        conversation_id,
        reason="Not covered.",
        options=OPTIONS,
        progress=RunProgress(latency_ms=1200, llm_calls=2, tokens=900),
    )
    return service, started.run_id


async def test_begin_run_stores_the_question_and_a_running_run_together() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)

    started = await service.begin_run(ALICE, conversation_id, question="Why?", workflow="qa")

    assert started.conversation_mode == "corpus_only"
    assert started.question.role == "user"
    assert started.question.content == "Why?"
    assert started.question.run_id == started.run_id
    assert store.runs[started.run_id].status == "running"
    assert store.commits == 1


async def test_begin_run_in_another_users_conversation_is_404_and_stores_nothing() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)

    with pytest.raises(NotFoundError):
        await service.begin_run(BOB, conversation_id, question="Why?", workflow="qa")

    assert store.messages == {}
    assert store.runs == {}


async def test_pause_logs_a_pending_approval_and_interrupts_with_the_progress() -> None:
    store = InMemoryConversationStore()
    _, run_id = await paused_run(store)

    run = store.runs[run_id]
    [approval] = store.approvals
    assert (run.status, run.latency_ms, run.llm_calls, run.tokens) == (
        "interrupted",
        1200,
        2,
        900,
    )
    assert approval.run_id == run_id
    assert approval.options == OPTIONS
    assert approval.decision is None


async def test_resume_records_the_decision_and_returns_the_progress() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    resumed = await service.resume_run(ALICE, run_id, "general_knowledge")

    assert resumed.decision == "general_knowledge"
    assert resumed.progress == RunProgress(latency_ms=1200, llm_calls=2, tokens=900)
    assert store.runs[run_id].status == "running"
    assert store.approvals[0].decision == "general_knowledge"
    assert store.approvals[0].decided_at is not None


async def test_resume_by_another_user_is_404_and_changes_nothing() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    with pytest.raises(NotFoundError):
        await service.resume_run(BOB, run_id, "corpus_only")

    assert store.runs[run_id].status == "interrupted"
    assert store.approvals[0].decision is None


async def test_resuming_twice_is_a_conflict() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)
    await service.resume_run(ALICE, run_id, "corpus_only")

    with pytest.raises(ConflictError):
        await service.resume_run(ALICE, run_id, "general_knowledge")

    assert store.approvals[0].decision == "corpus_only"


async def test_resuming_a_running_run_is_a_conflict() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)
    started = await service.begin_run(ALICE, conversation_id, question="Why?", workflow="qa")

    with pytest.raises(ConflictError):
        await service.resume_run(ALICE, started.run_id, "corpus_only")


async def test_a_decision_that_was_not_offered_is_invalid() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    with pytest.raises(InvalidInputError):
        await service.resume_run(ALICE, run_id, "anything_goes")

    assert store.runs[run_id].status == "interrupted"
    assert store.approvals[0].decision is None


async def test_fail_run_finishes_the_run_as_failed_whatever_its_state() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    await service.fail_run(ALICE, run_id, RunSummary(llm_calls=3, error="llm_unavailable: x"))

    run = store.runs[run_id]
    assert (run.status, run.llm_calls, run.error) == ("failed", 3, "llm_unavailable: x")
    assert run.finished_at is not None


async def test_stale_sweep_passes_the_cutoff_and_exclusions() -> None:
    store = InMemoryConversationStore()
    service, conversation_id = await conversation(store)
    kept = await service.begin_run(ALICE, conversation_id, question="a", workflow="qa")
    stale = await service.begin_run(ALICE, conversation_id, question="b", workflow="qa")

    count = await service.fail_stale_runs(
        older_than=timedelta(minutes=15), reason="restart", exclude={kept.run_id}
    )

    assert count == 1
    assert store.runs[stale.run_id].status == "failed"
    assert store.runs[kept.run_id].status == "running"


async def test_get_run_of_a_paused_run_includes_the_logged_request() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    run = await service.get_run(ALICE, run_id)

    assert run.status == "interrupted"
    assert run.pending_approval is not None
    assert (run.pending_approval.reason, run.pending_approval.options) == ("Not covered.", OPTIONS)


async def test_get_run_has_no_request_once_the_run_is_decided() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)
    await service.resume_run(ALICE, run_id, "corpus_only")

    run = await service.get_run(ALICE, run_id)

    assert (run.status, run.pending_approval) == ("running", None)


async def test_get_run_of_another_users_or_a_missing_run_is_404() -> None:
    store = InMemoryConversationStore()
    service, run_id = await paused_run(store)

    with pytest.raises(NotFoundError):
        await service.get_run(BOB, run_id)
    with pytest.raises(NotFoundError):
        await service.get_run(ALICE, uuid4())
