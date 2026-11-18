"""Background ingestion (SRS §8.1): uploaded → parsing → embedding → ready, or failed.

Each status change is committed on its own, so clients polling the document see progress.
Chunks, metadata, and `ready` are written in one transaction, so a ready document always has
all its chunks, and the document joins its workspaces' topic profiles in that transaction.
Afterwards, outside the transaction and the ingestion slot, those workspaces' keyword summaries
are refreshed (S7, D-068).
"""

import asyncio
import logging
import time
from collections.abc import Callable, Collection
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import DocumentParseError
from app.providers.embedding import EmbeddingProvider
from app.providers.parser import DocumentParser, ParsedPage
from app.repositories.documents import DocumentFields, NewChunk
from app.services.chunking import ChunkDraft, chunk_pages
from app.services.document_metadata import DocumentMetadata, MetadataService
from app.services.guardrails import clean_metadata_text, clean_optional, clean_untrusted_text
from app.services.page_cleanup import remove_repeated_lines
from app.services.topic_profile import CompatibilityOptions, TopicProfileService, TopicProfileStore

logger = logging.getLogger(__name__)

UNEXPECTED_FAILURE = "Ingestion failed unexpectedly. Delete the document and upload it again."
NO_TEXT = "No text could be extracted from the PDF."
INTERRUPTED = "Ingestion was interrupted (for example by a server restart). Upload the file again."


class IngestionStore(Protocol):
    """Persistence ingestion needs; `DocumentRepository` implements it."""

    @property
    def profiles(self) -> TopicProfileStore:
        """Topic profiles on the same session."""
        ...

    async def set_status(
        self, user_id: UUID, document_id: UUID, status: str, *, error: str | None = None
    ) -> bool: ...

    async def lock(self, user_id: UUID, document_id: UUID) -> bool: ...

    async def complete(
        self,
        user_id: UUID,
        document_id: UUID,
        fields: DocumentFields,
        chunks: list[NewChunk],
    ) -> None: ...

    async def fail_stale(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int: ...

    async def commit(self) -> None: ...


class SummaryRefresher(Protocol):
    """Refreshes a workspace's keyword summary; `TopicSummaryService` implements it."""

    async def refresh(self, user_id: UUID, workspace_id: UUID) -> None: ...


# Opens a store on a fresh session; the session closes (rolling back anything uncommitted)
# when the context exits.
StoreFactory = Callable[[], AbstractAsyncContextManager[IngestionStore]]


@dataclass(frozen=True)
class IngestionOptions:
    """Boilerplate removal and chunking parameters (SRS §8.1, D-044)."""

    boilerplate_min_pages: int
    boilerplate_min_page_fraction: float
    boilerplate_max_line_chars: int
    chunk_min_tokens: int
    chunk_max_tokens: int
    chunk_overlap_ratio: float
    chunk_merge_below_tokens: int
    chunk_hard_max_tokens: int
    concurrency: int
    stale_after: timedelta

    @classmethod
    def from_settings(cls, settings: Settings) -> "IngestionOptions":
        """Read the options from the application settings."""
        return cls(
            boilerplate_min_pages=settings.boilerplate_min_pages,
            boilerplate_min_page_fraction=settings.boilerplate_min_page_fraction,
            boilerplate_max_line_chars=settings.boilerplate_max_line_chars,
            chunk_min_tokens=settings.chunk_min_tokens,
            chunk_max_tokens=settings.chunk_max_tokens,
            chunk_overlap_ratio=settings.chunk_overlap_ratio,
            chunk_merge_below_tokens=settings.chunk_merge_below_tokens,
            chunk_hard_max_tokens=settings.chunk_hard_max_tokens,
            concurrency=settings.ingestion_concurrency,
            stale_after=timedelta(minutes=settings.ingestion_stale_minutes),
        )


class _Deleted(Exception):
    """The document was deleted while it was being ingested."""


class IngestionService:
    """Turns an uploaded PDF into metadata and embedded chunks, a few documents at a time."""

    def __init__(
        self,
        stores: StoreFactory,
        *,
        parser: DocumentParser,
        embedder: EmbeddingProvider,
        metadata: MetadataService,
        options: IngestionOptions,
        compatibility: CompatibilityOptions,
        summaries: SummaryRefresher | None = None,
    ) -> None:
        """Without `summaries`, workspace keyword summaries are not refreshed."""
        self._stores = stores
        self._summaries = summaries
        self._compatibility = compatibility
        self._parser = parser
        self._embedder = embedder
        self._metadata = metadata
        self._options = options
        # Extra documents wait here in status "uploaded".
        self._slots = asyncio.Semaphore(options.concurrency)
        # Queued or running here; the sweep must not fail these, however long they wait.
        self._active: set[UUID] = set()

    async def run(self, user_id: UUID, document_id: UUID, data: bytes) -> None:
        """Ingest one document. Never raises: failures are recorded on the document."""
        self._active.add(document_id)
        try:
            workspaces = await self._run(user_id, document_id, data)
        finally:
            self._active.discard(document_id)
        await self._refresh_summaries(user_id, workspaces)

    async def _run(self, user_id: UUID, document_id: UUID, data: bytes) -> list[UUID]:
        """Ingest in a slot; returns the workspaces the document joined once ready."""
        async with self._slots:
            started = time.perf_counter()
            try:
                pages, chunks, workspaces = await self._ingest(user_id, document_id, data)
            except _Deleted:
                logger.info("Document %s was deleted during ingestion", document_id)
            except DocumentParseError as error:
                logger.info("Document %s failed: %s", document_id, error.message)
                await self._fail(user_id, document_id, error.message)
            except Exception:
                logger.exception("Ingestion of document %s failed", document_id)
                await self._fail(user_id, document_id, UNEXPECTED_FAILURE)
            else:
                logger.info(
                    "Ingested document %s: %d pages, %d chunks in %.1f s",
                    document_id,
                    pages,
                    chunks,
                    time.perf_counter() - started,
                )
                return workspaces
            return []

    async def _refresh_summaries(self, user_id: UUID, workspaces: list[UUID]) -> None:
        if self._summaries is None:
            return
        for workspace_id in workspaces:
            try:
                await self._summaries.refresh(user_id, workspace_id)
            except Exception:
                # The document is ready; a summary failure must not fail it.
                logger.exception("Topic summary refresh of workspace %s failed", workspace_id)

    async def fail_stale(self) -> int:
        """Mark in-progress documents nobody is processing any more as failed (D-049, D-058).

        Documents queued or running in this process are skipped. A failed document can be
        uploaded again (the failed-duplicate path re-ingests it).
        """
        async with self._stores() as store:
            count = await store.fail_stale(
                older_than=self._options.stale_after,
                reason=INTERRUPTED,
                exclude=set(self._active),
            )
            await store.commit()
        if count:
            logger.warning("Marked %d interrupted ingestions as failed", count)
        return count

    async def sweep_periodically(self, interval_seconds: float) -> None:
        """Run `fail_stale` every `interval_seconds` until cancelled; errors are logged."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.fail_stale()
            except Exception:
                logger.exception("Periodic sweep of interrupted ingestions failed")

    async def _ingest(
        self, user_id: UUID, document_id: UUID, data: bytes
    ) -> tuple[int, int, list[UUID]]:
        await self._set_status(user_id, document_id, "parsing")
        parsed = await self._parser.parse(data)
        drafts = prepare_chunks(parsed.pages, self._embedder.count_tokens, self._options)
        if not drafts:
            raise DocumentParseError(NO_TEXT)

        await self._set_status(user_id, document_id, "embedding")
        # The metadata lookup waits on the network and the LLM, so it runs while the CPU embeds.
        lookup = asyncio.create_task(self._metadata.extract(parsed))
        try:
            vectors = await self._embedder.embed_documents([draft.text for draft in drafts])
        except BaseException:
            lookup.cancel()
            raise
        metadata = await lookup
        chunks = [
            _new_chunk(draft, vector, self._embedder.model_name)
            for draft, vector in zip(drafts, vectors, strict=True)
        ]
        async with self._stores() as store:
            if not await store.lock(user_id, document_id):
                raise _Deleted
            await store.complete(user_id, document_id, _fields(metadata, parsed.page_count), chunks)
            profiles = TopicProfileService(store.profiles, self._compatibility)
            await profiles.document_ready(user_id, document_id)
            workspaces = await store.profiles.linked_workspaces(user_id, document_id)
            await store.commit()
        return parsed.page_count, len(chunks), workspaces

    async def _set_status(self, user_id: UUID, document_id: UUID, status: str) -> None:
        async with self._stores() as store:
            if not await store.set_status(user_id, document_id, status):
                raise _Deleted
            await store.commit()

    async def _fail(self, user_id: UUID, document_id: UUID, reason: str) -> None:
        try:
            async with self._stores() as store:
                await store.set_status(user_id, document_id, "failed", error=reason)
                await store.commit()
        except Exception:
            # The startup sweep fails it later if it stays in progress.
            logger.exception("Could not mark document %s as failed", document_id)


def prepare_chunks(
    pages: list[ParsedPage], count_tokens: Callable[[str], int], options: IngestionOptions
) -> list[ChunkDraft]:
    """Clean untrusted text, drop boilerplate, and chunk (chunk hashes match stored text)."""
    safe = [
        page.model_copy(update={"markdown": clean_untrusted_text(page.markdown)}) for page in pages
    ]
    cleaned = remove_repeated_lines(
        safe,
        min_pages=options.boilerplate_min_pages,
        min_page_fraction=options.boilerplate_min_page_fraction,
        max_line_chars=options.boilerplate_max_line_chars,
    )
    return chunk_pages(
        cleaned.pages,
        count_tokens=count_tokens,
        min_tokens=options.chunk_min_tokens,
        max_tokens=options.chunk_max_tokens,
        overlap_ratio=options.chunk_overlap_ratio,
        merge_below_tokens=options.chunk_merge_below_tokens,
        hard_max_tokens=options.chunk_hard_max_tokens,
    )


def _new_chunk(draft: ChunkDraft, embedding: list[float], model: str) -> NewChunk:
    return NewChunk(
        chunk_index=draft.chunk_index,
        page_start=draft.page_start,
        page_end=draft.page_end,
        section=clean_optional(draft.section),
        text=draft.text,
        token_count=draft.token_count,
        content_hash=draft.content_hash,
        embedding=embedding,
        embedding_model=model,
    )


def _fields(metadata: DocumentMetadata, page_count: int) -> DocumentFields:
    authors = [author for author in map(clean_metadata_text, metadata.authors) if author]
    return DocumentFields(
        title=clean_metadata_text(metadata.title),
        authors=authors,
        year=metadata.year,
        venue=clean_metadata_text(metadata.venue),
        doi=clean_optional(metadata.doi),
        page_count=page_count,
    )
