"""Background ingestion with fake providers and an in-memory store (SRS §8.1)."""

import asyncio
import logging
from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.providers.fakes import FakeEmbedder, FakeParser, FakeScholarlySearch
from app.providers.parser import ParsedDocument
from app.providers.search import PaperRecord
from app.repositories.documents import DocumentFields, NewChunk
from app.repositories.topic_profiles import ProfileState
from app.services.document_metadata import MetadataService
from app.services.ingestion import (
    INTERRUPTED,
    NO_TEXT,
    UNEXPECTED_FAILURE,
    IngestionOptions,
    IngestionService,
)
from app.services.topic_profile import CompatibilityOptions
from tests.unit.profile_fakes import InMemoryProfileStore, LinkResult

USER = uuid4()
PAPER = (
    b"%PDF-fake\n"
    b"Title: Scaffold porosity\n"
    b"Author: A. Example; B. Sample\n"
    b"# Porosity of scaffolds\n"
    b"doi: 10.5555/fake.0001\n\n"
    b"Porous scaffolds improve fibroblast infiltration. Pore size matters.\n"
    b"\f"
    b"# Methods\n"
    b"Electrospinning produced PCL fibres with controlled diameter."
)


@dataclass
class Row:
    status: str = "uploaded"
    error: str | None = None
    fields: DocumentFields | None = None
    chunks: list[NewChunk] = field(default_factory=list)
    history: list[str] = field(default_factory=list)


class InMemoryIngestionStore:
    """Shared rows; every `open()` is one session, uncommitted changes are discarded."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Row] = {}
        self.owners: dict[UUID, UUID] = {}
        self.stale_calls: list[tuple[timedelta, str]] = []
        self.excluded: list[set[UUID]] = []
        self.sweep_error: Exception | None = None
        self.profiles = InMemoryProfileStore()

    def add(self, document_id: UUID, user_id: UUID = USER) -> Row:
        row = Row()
        self.rows[document_id] = row
        self.owners[document_id] = user_id
        return row

    @asynccontextmanager
    async def open(self) -> AsyncIterator["_Session"]:
        yield _Session(self)


class _Session:
    def __init__(self, store: InMemoryIngestionStore) -> None:
        self._store = store
        self._pending: list[
            tuple[UUID, str, str | None, DocumentFields | None, list[NewChunk]]
        ] = []

    @property
    def profiles(self) -> InMemoryProfileStore:
        return self._store.profiles

    def _row(self, user_id: UUID, document_id: UUID) -> Row | None:
        if self._store.owners.get(document_id) != user_id:
            return None
        return self._store.rows.get(document_id)

    async def set_status(
        self, user_id: UUID, document_id: UUID, status: str, *, error: str | None = None
    ) -> bool:
        if self._row(user_id, document_id) is None:
            return False
        self._pending.append((document_id, status, error, None, []))
        return True

    async def lock(self, user_id: UUID, document_id: UUID) -> bool:
        return self._row(user_id, document_id) is not None

    async def complete(
        self, user_id: UUID, document_id: UUID, fields: DocumentFields, chunks: list[NewChunk]
    ) -> None:
        self._pending.append((document_id, "ready", None, fields, list(chunks)))
        self.profiles.chunks[document_id] = (user_id, [chunk.embedding for chunk in chunks])

    async def fail_stale(
        self, *, older_than: timedelta, reason: str, exclude: Collection[UUID] = ()
    ) -> int:
        self._store.stale_calls.append((older_than, reason))
        self._store.excluded.append(set(exclude))
        if self._store.sweep_error is not None:
            raise self._store.sweep_error
        return 2

    async def commit(self) -> None:
        for document_id, status, error, fields, chunks in self._pending:
            row = self._store.rows.get(document_id)
            if row is None:
                continue
            row.status, row.error = status, error
            row.history.append(status)
            if fields is not None:
                row.fields, row.chunks = fields, chunks
        self._pending = []


class TrackingParser(FakeParser):
    """Counts parses running at the same time; each takes a little while."""

    def __init__(self) -> None:
        self.running = 0
        self.max_running = 0

    async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(0.02)
            return await super().parse(data, max_pages=max_pages)
        finally:
            self.running -= 1


class BrokenParser(FakeParser):
    async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
        raise RuntimeError("segfault-ish")


@pytest.fixture
def store() -> InMemoryIngestionStore:
    return InMemoryIngestionStore()


def service(
    store: InMemoryIngestionStore,
    *,
    parser: FakeParser | None = None,
    concurrency: int = 1,
    stale_minutes: int = 15,
    summaries: "RecordingSummaries | None" = None,
) -> IngestionService:
    settings = Settings(
        _env_file=None,
        ingestion_concurrency=concurrency,
        ingestion_stale_minutes=stale_minutes,
        chunk_min_tokens=5,
        chunk_max_tokens=20,
        chunk_hard_max_tokens=40,
        chunk_merge_below_tokens=0,
    )
    return IngestionService(
        store.open,
        parser=parser or FakeParser(),
        embedder=FakeEmbedder(dimension=384),
        metadata=MetadataService(FakeScholarlySearch(), max_candidates=3),
        options=IngestionOptions.from_settings(settings),
        compatibility=CompatibilityOptions.from_settings(settings),
        summaries=summaries,
    )


@dataclass
class RecordingSummaries:
    """Records keyword summary refreshes and the document status each one saw."""

    store: InMemoryIngestionStore
    seen: list[tuple[UUID, UUID, str]] = field(default_factory=list)
    error: Exception | None = None

    async def refresh(self, user_id: UUID, workspace_id: UUID) -> None:
        statuses = {row.status for row in self.store.rows.values()}
        self.seen.append((user_id, workspace_id, ",".join(sorted(statuses))))
        if self.error is not None:
            raise self.error


async def test_ready_document_has_metadata_and_embedded_chunks(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()
    row = store.add(document_id)

    await service(store).run(USER, document_id, PAPER)

    assert row.history == ["parsing", "embedding", "ready"]
    assert row.status == "ready"
    assert row.error is None
    assert row.fields is not None
    assert row.fields.page_count == 2
    # Confirmed by the (fake) lookup, so its metadata wins over the PDF's (D-056).
    assert row.fields.doi == "10.5555/fake.0001"
    assert row.fields.authors == ["A. Example", "B. Sample"]
    assert row.fields.year == 2021
    assert row.chunks
    assert [chunk.chunk_index for chunk in row.chunks] == list(range(len(row.chunks)))
    assert {chunk.embedding_model for chunk in row.chunks} == {"fake-hash-384-v1"}
    assert all(len(chunk.embedding) == 384 for chunk in row.chunks)
    assert {chunk.page_start for chunk in row.chunks} == {1, 2}
    assert "Methods" in {chunk.section for chunk in row.chunks}


async def test_ready_document_joins_its_workspace_profile_with_a_score(
    store: InMemoryIngestionStore,
) -> None:
    document_id, workspace = uuid4(), uuid4()
    store.add(document_id)
    store.profiles.workspaces[workspace] = USER
    store.profiles.links[(workspace, document_id)] = LinkResult(override=True)
    existing = [1.0] + [0.0] * 383
    store.profiles.profiles[workspace] = ProfileState(centroid=existing, document_count=1)

    await service(store).run(USER, document_id, PAPER)

    link = store.profiles.links[(workspace, document_id)]
    assert link.score is not None
    assert link.override is True
    profile = store.profiles.profiles[workspace]
    assert profile.document_count == 2
    assert profile.centroid != existing


async def test_control_characters_are_removed_before_storing(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()
    row = store.add(document_id)
    paper = (
        b"%PDF-fake\nTitle: Null\x00 title\x07\n# Res\x00ults\n"
        b"Cells\x00 grew\x1b on \x0bscaffolds.\tTabs and\nnewlines stay."
    )

    await service(store).run(USER, document_id, paper)

    assert row.status == "ready"
    stored = " ".join(chunk.text for chunk in row.chunks)
    assert "Cells grew on scaffolds." in stored
    assert not any(ch in stored for ch in "\x00\x07\x0b\x1b")
    assert {chunk.section for chunk in row.chunks} == {"Results"}


async def test_unreadable_document_fails_with_the_parser_reason(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()
    row = store.add(document_id)

    await service(store).run(USER, document_id, b"%PDF-1.7 real pdf bytes")

    assert row.history == ["parsing", "failed"]
    assert row.error is not None
    assert "fake parser cannot read real PDFs" in row.error
    assert row.chunks == []


async def test_document_without_text_fails(store: InMemoryIngestionStore) -> None:
    document_id = uuid4()
    row = store.add(document_id)

    await service(store).run(USER, document_id, b"%PDF-fake\n\f\n")

    assert row.status == "failed"
    assert row.error == NO_TEXT


async def test_unexpected_error_fails_with_a_generic_reason(
    store: InMemoryIngestionStore, caplog: pytest.LogCaptureFixture
) -> None:
    document_id = uuid4()
    row = store.add(document_id)

    await service(store, parser=BrokenParser()).run(USER, document_id, PAPER)

    assert row.status == "failed"
    assert row.error == UNEXPECTED_FAILURE
    assert "segfault-ish" in caplog.text  # logged with the traceback, not shown to the user


async def test_document_deleted_before_ingestion_is_skipped(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()  # never added: deleted before the task started

    await service(store).run(USER, document_id, PAPER)

    assert store.rows == {}


async def test_document_deleted_during_ingestion_is_not_failed(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()
    store.add(document_id)

    class DeletingParser(FakeParser):
        async def parse(self, data: bytes, *, max_pages: int | None = None) -> ParsedDocument:
            del store.rows[document_id]
            del store.owners[document_id]
            return await super().parse(data, max_pages=max_pages)

    await service(store, parser=DeletingParser()).run(USER, document_id, PAPER)

    assert store.rows == {}


async def test_another_users_document_is_never_touched(store: InMemoryIngestionStore) -> None:
    document_id = uuid4()
    row = store.add(document_id, user_id=uuid4())

    await service(store).run(USER, document_id, PAPER)

    assert row.history == []


async def test_two_uploads_do_not_parse_at_the_same_time(
    store: InMemoryIngestionStore,
) -> None:
    parser = TrackingParser()
    ingestion = service(store, parser=parser, concurrency=1)
    first, second = uuid4(), uuid4()
    store.add(first)
    second_row = store.add(second)

    first_run = asyncio.create_task(ingestion.run(USER, first, PAPER))
    await asyncio.sleep(0.005)
    # The second waits for a slot without leaving "uploaded".
    second_run = asyncio.create_task(ingestion.run(USER, second, PAPER + b" more"))
    await asyncio.sleep(0.005)
    assert parser.running == 1
    assert second_row.history == []
    await asyncio.gather(first_run, second_run)

    assert parser.max_running == 1
    assert store.rows[first].status == "ready"
    assert second_row.status == "ready"


async def test_concurrency_setting_allows_parallel_ingestions(
    store: InMemoryIngestionStore,
) -> None:
    parser = TrackingParser()
    ingestion = service(store, parser=parser, concurrency=2)
    first, second = uuid4(), uuid4()
    store.add(first)
    store.add(second)

    await asyncio.gather(ingestion.run(USER, first, PAPER), ingestion.run(USER, second, PAPER))

    assert parser.max_running == 2


async def test_fail_stale_uses_the_configured_age(
    store: InMemoryIngestionStore, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    count = await service(store, stale_minutes=7).fail_stale()

    assert count == 2
    assert store.stale_calls == [(timedelta(minutes=7), INTERRUPTED)]
    assert "Marked 2 interrupted ingestions as failed" in caplog.text


async def test_failure_to_record_a_failure_is_logged(
    store: InMemoryIngestionStore, caplog: pytest.LogCaptureFixture
) -> None:
    document_id = uuid4()
    store.add(document_id)
    ingestion = service(store, parser=BrokenParser())
    calls = 0

    @asynccontextmanager
    async def flaky() -> AsyncIterator[_Session]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ConnectionError("database down")
        yield _Session(store)

    ingestion._stores = flaky

    await ingestion.run(USER, document_id, PAPER)

    assert "Could not mark document" in caplog.text


async def test_html_markup_in_pdf_metadata_is_removed(store: InMemoryIngestionStore) -> None:
    document_id = uuid4()
    row = store.add(document_id)
    # The title from the known issue (task #6): markup in the PDF's own metadata.
    paper = (
        b"%PDF-fake\n"
        b"Title: <u><mark>Additive manufacturing and performance of bioceramic scaffolds "
        b"with different hollow strut geometries</mark></u>\n"
        b"Author: Shumin <i>Pang</i>; A. Example &amp; B. Sample\n"
        b"# Results\nStruts were hollow."
    )

    await service(store).run(USER, document_id, paper)

    assert row.fields is not None
    assert row.fields.title == (
        "Additive manufacturing and performance of bioceramic scaffolds "
        "with different hollow strut geometries"
    )
    assert row.fields.authors == ["Shumin Pang", "A. Example", "B. Sample"]


class MarkupLookup(FakeScholarlySearch):
    """Confirms every DOI with a Crossref-style record full of markup."""

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        return PaperRecord(
            source="crossref",
            external_id=doi,
            doi=doi,
            title="Ca<sub>3</sub>(PO<sub>4</sub>)<sub>2</sub> scaffolds &amp; <i>in vivo</i> bone",
            authors=["J. <b>Doe</b>", "&lt;i&gt;A.&lt;/i&gt; Smith"],
            year=2024,
            venue="<i>Acta Biomaterialia</i>",
        )


async def test_html_markup_from_the_doi_lookup_is_removed(store: InMemoryIngestionStore) -> None:
    document_id = uuid4()
    row = store.add(document_id)
    ingestion = service(store)
    ingestion._metadata = MetadataService(MarkupLookup(), max_candidates=3)

    await ingestion.run(USER, document_id, PAPER)

    assert row.fields is not None
    assert row.fields.title == "Ca3(PO4)2 scaffolds & in vivo bone"
    assert row.fields.authors == ["J. Doe", "A. Smith"]
    assert row.fields.venue == "Acta Biomaterialia"


class SlowLookup(FakeScholarlySearch):
    """A DOI lookup that takes a while and records whether it is in flight or was cancelled."""

    def __init__(self) -> None:
        super().__init__()
        self.running = False
        self.cancelled = False

    async def get_by_doi(self, doi: str) -> PaperRecord | None:
        self.running = True
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.running = False
        return await super().get_by_doi(doi)


class LookupWatchingEmbedder(FakeEmbedder):
    """Notes whether the metadata lookup is in flight while embedding; can fail instead."""

    def __init__(self, lookup: SlowLookup, *, fail: bool = False) -> None:
        super().__init__(dimension=384)
        self.lookup = lookup
        self.fail = fail
        self.saw_lookup_running = False

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        await asyncio.sleep(0.01)
        self.saw_lookup_running = self.lookup.running
        if self.fail:
            raise RuntimeError("out of memory")
        return await super().embed_documents(texts)


async def test_metadata_lookup_runs_while_embedding(store: InMemoryIngestionStore) -> None:
    document_id = uuid4()
    row = store.add(document_id)
    lookup = SlowLookup()
    ingestion = service(store)
    ingestion._metadata = MetadataService(lookup, max_candidates=3)
    ingestion._embedder = embedder = LookupWatchingEmbedder(lookup)

    await ingestion.run(USER, document_id, PAPER)

    assert embedder.saw_lookup_running
    assert row.status == "ready"
    assert row.fields is not None and row.fields.title


async def test_embedding_failure_cancels_the_metadata_lookup(
    store: InMemoryIngestionStore,
) -> None:
    document_id = uuid4()
    row = store.add(document_id)
    lookup = SlowLookup()
    ingestion = service(store)
    ingestion._metadata = MetadataService(lookup, max_candidates=3)
    ingestion._embedder = LookupWatchingEmbedder(lookup, fail=True)

    await ingestion.run(USER, document_id, PAPER)
    await asyncio.sleep(0)

    assert lookup.cancelled
    assert row.status == "failed"
    assert row.error == UNEXPECTED_FAILURE


async def test_periodic_sweep_repeats_and_survives_errors(
    store: InMemoryIngestionStore, caplog: pytest.LogCaptureFixture
) -> None:
    store.sweep_error = ConnectionError("database down")
    sweeper = asyncio.create_task(service(store).sweep_periodically(0.01))

    await asyncio.sleep(0.1)
    assert not sweeper.done()  # errors are logged, not raised
    store.sweep_error = None
    await asyncio.sleep(0.05)
    sweeper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sweeper

    assert len(store.stale_calls) >= 3
    assert "Periodic sweep of interrupted ingestions failed" in caplog.text


async def test_sweep_skips_documents_queued_or_running_here(
    store: InMemoryIngestionStore,
) -> None:
    parser = TrackingParser()
    ingestion = service(store, parser=parser, concurrency=1)
    running, queued = uuid4(), uuid4()
    store.add(running)
    store.add(queued)
    tasks = [
        asyncio.create_task(ingestion.run(USER, running, PAPER)),
        asyncio.create_task(ingestion.run(USER, queued, PAPER + b" more")),
    ]
    await asyncio.sleep(0.005)

    await ingestion.fail_stale()
    await asyncio.gather(*tasks)
    await ingestion.fail_stale()

    assert store.excluded == [{running, queued}, set()]


# --- Keyword summary refresh (S7, D-068) ---


async def test_ready_document_refreshes_its_workspaces_summaries_after_commit(
    store: InMemoryIngestionStore,
) -> None:
    document_id, first, second, foreign = uuid4(), uuid4(), uuid4(), uuid4()
    store.add(document_id)
    for workspace in (first, second):
        store.profiles.workspaces[workspace] = USER
        store.profiles.links[(workspace, document_id)] = LinkResult()
    store.profiles.workspaces[foreign] = uuid4()
    store.profiles.links[(foreign, document_id)] = LinkResult()
    summaries = RecordingSummaries(store)

    await service(store, summaries=summaries).run(USER, document_id, PAPER)

    # Called with the document already committed as ready, and only for the user's workspaces.
    assert summaries.seen == [(USER, w, "ready") for w in sorted([first, second])]


async def test_failed_document_refreshes_no_summary(store: InMemoryIngestionStore) -> None:
    document_id, workspace = uuid4(), uuid4()
    store.add(document_id)
    store.profiles.workspaces[workspace] = USER
    store.profiles.links[(workspace, document_id)] = LinkResult()
    summaries = RecordingSummaries(store)

    await service(store, summaries=summaries).run(USER, document_id, b"%PDF-fake\n\f\n")

    assert summaries.seen == []


async def test_summary_failure_leaves_the_document_ready(
    store: InMemoryIngestionStore, caplog: pytest.LogCaptureFixture
) -> None:
    document_id, workspace = uuid4(), uuid4()
    row = store.add(document_id)
    store.profiles.workspaces[workspace] = USER
    store.profiles.links[(workspace, document_id)] = LinkResult()
    summaries = RecordingSummaries(store, error=RuntimeError("summary store down"))

    await service(store, summaries=summaries).run(USER, document_id, PAPER)

    assert row.status == "ready"
    assert row.history == ["parsing", "embedding", "ready"]
    assert "summary store down" in caplog.text
