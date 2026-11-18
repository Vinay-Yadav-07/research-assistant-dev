"""S7 keyword summary with a fake LLM and an in-memory store (D-068)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.core.errors import LLMQuotaExceededError
from app.providers.fakes import FakeLLM
from app.repositories.topic_profiles import SummaryDocument
from app.services.topic_summary import TopicSummary, TopicSummaryOptions, TopicSummaryService

USER = uuid4()
WORKSPACE = uuid4()


@dataclass
class Saved:
    keywords: list[str] | None
    summary: str | None


@dataclass
class InMemorySummaryStore:
    """Workspace owners, ready documents (newest first), and saved summaries."""

    owners: dict[UUID, UUID] = field(default_factory=dict)
    documents: dict[UUID, list[SummaryDocument]] = field(default_factory=dict)
    saved: dict[UUID, Saved] = field(default_factory=dict)
    commits: int = 0
    limits: list[int] = field(default_factory=list)

    @asynccontextmanager
    async def open(self) -> AsyncIterator["InMemorySummaryStore"]:
        yield self

    async def summary_documents(
        self, user_id: UUID, workspace_id: UUID, *, limit: int
    ) -> list[SummaryDocument] | None:
        self.limits.append(limit)
        if self.owners.get(workspace_id) != user_id:
            return None
        return self.documents.get(workspace_id, [])[:limit]

    async def save_summary(
        self, user_id: UUID, workspace_id: UUID, *, keywords: list[str] | None, summary: str | None
    ) -> None:
        assert self.owners.get(workspace_id) == user_id
        self.saved[workspace_id] = Saved(keywords, summary)

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def store() -> InMemorySummaryStore:
    return InMemorySummaryStore(
        owners={WORKSPACE: USER},
        documents={
            WORKSPACE: [
                SummaryDocument(title="Porous scaffolds", text="Abstract: pore size matters."),
                SummaryDocument(title=None, text="Hydrogels for cartilage repair."),
            ]
        },
    )


def service(
    store: InMemorySummaryStore,
    llm: FakeLLM,
    *,
    max_documents: int = 20,
    chars_per_document: int = 1500,
) -> TopicSummaryService:
    return TopicSummaryService(
        store.open,
        llm,
        TopicSummaryOptions(max_documents=max_documents, chars_per_document=chars_per_document),
    )


def reply(**fields: object) -> TopicSummary:
    values: dict[str, object] = {
        "keywords": ["tissue engineering", "scaffolds", "hydrogels"],
        "summary": "Scaffolds and hydrogels for tissue repair.",
    }
    values.update(fields)
    return TopicSummary.model_validate(values)


async def test_refresh_saves_keywords_and_summary(store: InMemorySummaryStore) -> None:
    llm = FakeLLM(structured={TopicSummary: [reply()]})

    await service(store, llm).refresh(USER, WORKSPACE)

    assert store.saved[WORKSPACE] == Saved(
        ["tissue engineering", "scaffolds", "hydrogels"],
        "Scaffolds and hydrogels for tissue repair.",
    )
    assert store.commits == 1


async def test_documents_are_sent_as_data_blocks_cut_to_the_limit(
    store: InMemorySummaryStore,
) -> None:
    llm = FakeLLM(structured={TopicSummary: [reply()]})

    await service(store, llm, chars_per_document=12).refresh(USER, WORKSPACE)

    system, user = llm.calls[0].messages
    assert system.content.startswith("You describe the research topic of a workspace")
    assert user.content.count("<document>") == 2
    assert "Title: Porous scaffolds\nAbstract: po\n</document>" in user.content
    assert "Title: Untitled\nHydrogels fo\n</document>" in user.content
    assert llm.calls[0].temperature == 0


async def test_document_count_is_capped(store: InMemorySummaryStore) -> None:
    llm = FakeLLM(structured={TopicSummary: [reply()]})

    await service(store, llm, max_documents=1).refresh(USER, WORKSPACE)

    assert store.limits == [1]
    assert llm.calls[0].messages[1].content.count("<document>") == 1


async def test_keywords_are_cleaned_and_deduplicated(store: InMemorySummaryStore) -> None:
    llm = FakeLLM(
        structured={
            TopicSummary: [
                reply(
                    keywords=["Scaffolds", " scaffolds ", "<i>in vivo</i>", "", "hydrogels"],
                    summary="Two  lines\nof summary.",
                )
            ]
        }
    )

    await service(store, llm).refresh(USER, WORKSPACE)

    assert store.saved[WORKSPACE] == Saved(
        ["Scaffolds", "in vivo", "hydrogels"], "Two lines of summary."
    )


async def test_empty_workspace_is_cleared_without_an_llm_call(
    store: InMemorySummaryStore,
) -> None:
    store.documents[WORKSPACE] = []
    store.saved[WORKSPACE] = Saved(["old"], "Old summary.")
    llm = FakeLLM()

    await service(store, llm).refresh(USER, WORKSPACE)

    assert store.saved[WORKSPACE] == Saved(None, None)
    assert llm.calls == []


@pytest.mark.parametrize(
    "failure",
    [LLMQuotaExceededError("Daily LLM quota reached."), {"keywords": [], "summary": "x"}],
    ids=["provider-error", "invalid-output"],
)
async def test_llm_failure_keeps_the_old_summary(
    store: InMemorySummaryStore, failure: object
) -> None:
    store.saved[WORKSPACE] = Saved(["old"], "Old summary.")
    llm = FakeLLM(structured={TopicSummary: [failure]})  # type: ignore[list-item]

    await service(store, llm).refresh(USER, WORKSPACE)

    assert store.saved[WORKSPACE] == Saved(["old"], "Old summary.")
    assert store.commits == 0


async def test_another_users_workspace_is_never_touched(store: InMemorySummaryStore) -> None:
    llm = FakeLLM()

    await service(store, llm).refresh(uuid4(), WORKSPACE)

    assert store.saved == {}
    assert llm.calls == []


async def test_refreshes_of_one_workspace_run_one_at_a_time(
    store: InMemorySummaryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = 0
    most = 0

    async def slow_summary(documents: list[SummaryDocument]) -> TopicSummary:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01)
        running -= 1
        return reply()

    other = uuid4()
    store.owners[other] = USER
    store.documents[other] = store.documents[WORKSPACE]
    summaries = service(store, FakeLLM())
    monkeypatch.setattr(summaries, "_summarize", slow_summary)

    await asyncio.gather(*(summaries.refresh(USER, WORKSPACE) for _ in range(3)))
    assert most == 1

    await asyncio.gather(summaries.refresh(USER, WORKSPACE), summaries.refresh(USER, other))
    assert most == 2
