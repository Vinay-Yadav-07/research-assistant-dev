"""S7 keyword summary (SRS §5.3, D-068): keywords and a short summary of a workspace's topic.

One strong-tier call reads the titles and first chunks of the workspace's most recently added
ready documents. It runs in the background after a document becomes ready, is linked, or is
removed; an empty workspace is cleared without a call, and a failed call keeps the old summary.
Refreshes of one workspace run one at a time, so the last one reads the latest documents.
"""

import asyncio
import logging
import weakref
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.prompts import load_prompt
from app.providers.llm import ChatMessage, LLMProvider
from app.repositories.topic_profiles import SummaryDocument
from app.services.guardrails import clean_metadata_text, data_block

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


class TopicSummary(BaseModel):
    """The LLM's description of a workspace's topic."""

    keywords: list[str] = Field(min_length=1, max_length=15)
    summary: str = Field(min_length=1)


class TopicSummaryStore(Protocol):
    """Persistence the summary needs; `TopicProfileRepository` implements it."""

    async def summary_documents(
        self, user_id: UUID, workspace_id: UUID, *, limit: int
    ) -> list[SummaryDocument] | None: ...

    async def save_summary(
        self, user_id: UUID, workspace_id: UUID, *, keywords: list[str] | None, summary: str | None
    ) -> None: ...

    async def commit(self) -> None: ...


# Opens a store on a fresh session; the session closes when the context exits.
SummaryStoreFactory = Callable[[], AbstractAsyncContextManager[TopicSummaryStore]]


@dataclass(frozen=True)
class TopicSummaryOptions:
    """How many documents the summary reads, and how much of each."""

    max_documents: int
    chars_per_document: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "TopicSummaryOptions":
        """Read the options from the application settings."""
        return cls(
            max_documents=settings.topic_summary_max_documents,
            chars_per_document=settings.topic_summary_chars_per_document,
        )


class TopicSummaryService:
    """Keeps each workspace's keywords and summary in step with its ready documents.

    Give it the strong-tier LLM: the input holds many documents.
    """

    def __init__(
        self, stores: SummaryStoreFactory, llm: LLMProvider, options: TopicSummaryOptions
    ) -> None:
        self._stores = stores
        self._llm = llm
        self._options = options
        self._locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = weakref.WeakValueDictionary()

    async def refresh(self, user_id: UUID, workspace_id: UUID) -> None:
        """Summarize the workspace again. An LLM failure is logged and keeps the old summary."""
        lock = self._locks.get(workspace_id)
        if lock is None:
            lock = self._locks[workspace_id] = asyncio.Lock()
        async with lock:
            try:
                await self._refresh(user_id, workspace_id)
            except ExternalServiceError as error:
                logger.warning(
                    "Topic summary of workspace %s not updated: %s", workspace_id, error.message
                )

    async def _refresh(self, user_id: UUID, workspace_id: UUID) -> None:
        async with self._stores() as store:
            documents = await store.summary_documents(
                user_id, workspace_id, limit=self._options.max_documents
            )
        if documents is None:
            return
        keywords: list[str] | None = None
        summary: str | None = None
        if documents:
            result = await self._summarize(documents)
            keywords = _unique(result.keywords)
            summary = clean_metadata_text(result.summary)
        # The LLM call ran without a session; the write opens a new one.
        async with self._stores() as store:
            await store.save_summary(
                user_id, workspace_id, keywords=keywords or None, summary=summary
            )
            await store.commit()

    async def _summarize(self, documents: Sequence[SummaryDocument]) -> TopicSummary:
        blocks = [
            data_block(
                "document",
                f"Title: {document.title or 'Untitled'}\n"
                + document.text[: self._options.chars_per_document],
            )
            for document in documents
        ]
        messages = [
            ChatMessage(
                role="system", content=load_prompt("services", "topic_summary", PROMPT_VERSION)
            ),
            ChatMessage(role="user", content="\n\n".join(blocks)),
        ]
        result = await self._llm.generate_structured(messages, TopicSummary, temperature=0)
        return result.output


def _unique(keywords: Sequence[str]) -> list[str]:
    """Cleaned keywords without empty entries or case-insensitive repeats, in order."""
    seen: set[str] = set()
    unique: list[str] = []
    for keyword in keywords:
        cleaned = clean_metadata_text(keyword)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            unique.append(cleaned)
    return unique
