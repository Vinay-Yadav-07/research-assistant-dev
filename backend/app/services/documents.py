"""Document upload, listing, download, linking, and removal (FR-03, SRS §8.1, §20).

Missing and non-owned workspaces and documents raise NotFoundError (D-047).
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.core.errors import (
    ConflictError,
    DependencyUnavailableError,
    FileTooLargeError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.models.document import Document
from app.schemas.documents import (
    DocumentFileUrl,
    DocumentRead,
    DocumentSource,
    DocumentUploadResult,
)
from app.services.topic_profile import TopicProfileService

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
# The PDF header may follow a little leading junk; readers search the first 1 KB.
PDF_MAGIC_WINDOW = 1024
READ_CHUNK_BYTES = 1024 * 1024

# (user_id, document_id, file bytes): starts background ingestion after the response.
IngestionScheduler = Callable[[UUID, UUID, bytes], None]
# (user_id, workspace_id): refreshes the workspace keyword summary after the response (D-068).
SummaryScheduler = Callable[[UUID, UUID], None]


class DocumentStore(Protocol):
    """Persistence the service needs; `DocumentRepository` implements it."""

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool: ...

    async def get(self, user_id: UUID, document_id: UUID) -> Document | None: ...

    async def find_by_hash(self, user_id: UUID, content_hash: str) -> Document | None: ...

    async def create(
        self,
        user_id: UUID,
        document_id: UUID,
        *,
        content_hash: str,
        storage_path: str,
        source: DocumentSource = "upload",
        source_url: str | None = None,
    ) -> Document | None: ...

    async def is_linked(self, user_id: UUID, workspace_id: UUID, document_id: UUID) -> bool: ...

    async def lock(self, user_id: UUID, document_id: UUID) -> bool: ...

    async def link(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        compatibility_score: float | None = None,
        override: bool = False,
    ) -> None: ...

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Document]: ...

    async def unlink(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID
    ) -> tuple[bool, str | None]: ...

    async def restart(self, user_id: UUID, document_id: UUID) -> Document | None: ...

    async def commit(self) -> None: ...


class FileStorage(Protocol):
    """Private file storage; `SupabaseStorage` implements it."""

    async def upload_pdf(self, path: str, data: bytes) -> None: ...

    async def signed_url(self, path: str, *, expires_in: int) -> tuple[str, datetime]: ...

    async def delete(self, paths: list[str]) -> None: ...


async def read_upload(read: Callable[[int], Awaitable[bytes]], *, max_bytes: int) -> bytes:
    """Read an uploaded file, stopping as soon as it exceeds `max_bytes`."""
    parts: list[bytes] = []
    size = 0
    while part := await read(READ_CHUNK_BYTES):
        size += len(part)
        if size > max_bytes:
            raise FileTooLargeError(
                f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
                details={"max_bytes": max_bytes},
            )
        parts.append(part)
    return b"".join(parts)


def check_pdf(data: bytes) -> None:
    """Reject anything that is not a PDF by its content, whatever its name or declared type."""
    if not data:
        raise UnsupportedFileTypeError("The file is empty. Upload a PDF.")
    if PDF_MAGIC not in data[:PDF_MAGIC_WINDOW]:
        raise UnsupportedFileTypeError(
            "Only PDF files are accepted. Export the paper as PDF and upload it again."
        )


def storage_path_for(user_id: UUID, document_id: UUID) -> str:
    """Where a document's PDF is stored in the bucket."""
    return f"{user_id}/{document_id}.pdf"


async def remove_stored_files(storage: FileStorage | None, paths: list[str]) -> None:
    """Delete files after their records were deleted. Failures leave orphans and are logged."""
    if not paths:
        return
    if storage is None:
        logger.warning("Storage is not configured; %d stored files not deleted", len(paths))
        return
    try:
        await storage.delete(paths)
    except Exception:
        logger.exception("Could not delete %d stored files", len(paths))


class DocumentService:
    """Request-scoped operations on one user's documents."""

    def __init__(
        self,
        store: DocumentStore,
        storage: FileStorage | None,
        schedule_ingestion: IngestionScheduler,
        *,
        profiles: TopicProfileService,
        signed_url_ttl_seconds: int,
        schedule_summary: SummaryScheduler | None = None,
    ) -> None:
        """Without `schedule_summary`, linking and removal leave keyword summaries as they are."""
        self._store = store
        self._schedule_summary = schedule_summary
        self._profiles = profiles
        self._storage = storage
        self._schedule = schedule_ingestion
        self._signed_url_ttl = signed_url_ttl_seconds

    async def upload(
        self,
        user_id: UUID,
        workspace_id: UUID,
        data: bytes,
        *,
        override: bool = False,
        source: DocumentSource = "upload",
        source_url: str | None = None,
    ) -> DocumentUploadResult:
        """Store a new PDF and start ingestion, or report the user's existing copy.

        A previously failed copy is ingested again (SRS §20: allow re-upload). `override`
        records that the user chose "Import anyway" after a compatibility warning (FR-22);
        the score itself is recorded when the document is ready. `source` and `source_url`
        mark a paper imported from Discover (FR-17); an existing copy keeps its own.
        """
        await self._require_workspace(user_id, workspace_id)
        check_pdf(data)
        storage = self._require_storage()
        content_hash = hashlib.sha256(data).hexdigest()

        existing = await self._store.find_by_hash(user_id, content_hash)
        if existing is None:
            document_id = uuid4()
            path = storage_path_for(user_id, document_id)
            created = await self._store.create(
                user_id,
                document_id,
                content_hash=content_hash,
                storage_path=path,
                source=source,
                source_url=source_url,
            )
            if created is not None:
                await storage.upload_pdf(path, data)
                return await self._link_and_ingest(
                    user_id, workspace_id, created, data, [path], override=override
                )
            # A concurrent upload of the same file won the insert.
            existing = await self._store.find_by_hash(user_id, content_hash)
            if existing is None:
                raise ConflictError("The same file is being uploaded or deleted; try again.")

        if existing.status == "failed":
            restarted = await self._store.restart(user_id, existing.id)
            if restarted is not None:
                return await self._link_and_ingest(
                    user_id, workspace_id, restarted, data, [], override=override
                )

        linked = await self._store.is_linked(user_id, workspace_id, existing.id)
        return DocumentUploadResult(
            document=DocumentRead.model_validate(existing), duplicate=True, linked=linked
        )

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[DocumentRead]:
        """Documents linked to an owned workspace, most recently added first."""
        await self._require_workspace(user_id, workspace_id)
        documents = await self._store.list_in_workspace(
            user_id, workspace_id, limit=limit, offset=offset
        )
        return [DocumentRead.model_validate(document) for document in documents]

    async def get(self, user_id: UUID, document_id: UUID) -> DocumentRead:
        """One owned document."""
        return DocumentRead.model_validate(await self._require_document(user_id, document_id))

    async def file_url(self, user_id: UUID, document_id: UUID) -> DocumentFileUrl:
        """A short-lived signed URL for the owned document's PDF (NFR-09)."""
        document = await self._require_document(user_id, document_id)
        if document.storage_path is None:
            raise NotFoundError("This document has no stored file.")
        url, expires_at = await self._require_storage().signed_url(
            document.storage_path, expires_in=self._signed_url_ttl
        )
        return DocumentFileUrl(url=url, expires_at=expires_at)

    async def link(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID, *, override: bool = False
    ) -> DocumentRead:
        """Link an owned document to an owned workspace (e.g. a duplicate upload); idempotent.

        A ready document is checked against the workspace topic profile first (FR-22): below
        the threshold, `CompatibilityWarningError` is raised unless `override` is true, and
        the workspace keyword summary is refreshed afterwards. A document still being ingested
        is scored when it becomes ready.
        """
        await self._require_workspace(user_id, workspace_id)
        # The lock serializes this with ingestion finishing and with removal.
        if not await self._store.lock(user_id, document_id):
            raise NotFoundError("Document not found.")
        document = await self._require_document(user_id, document_id)
        result = DocumentRead.model_validate(document)
        if await self._store.is_linked(user_id, workspace_id, document_id):
            return result
        score = None
        if document.status == "ready":
            score = await self._profiles.include(
                user_id, workspace_id, document_id, override=override
            )
        await self._store.link(
            workspace_id, document_id, compatibility_score=score, override=override
        )
        await self._store.commit()
        if document.status == "ready":
            self._summary_changed(user_id, workspace_id)
        return result

    async def remove(self, user_id: UUID, workspace_id: UUID, document_id: UUID) -> None:
        """Unlink the document; delete it, its chunks, and its file if no workspace uses it.

        A ready document is first taken out of the workspace topic profile, and the workspace
        keyword summary is refreshed afterwards.
        """
        missing = NotFoundError("Document not found in this workspace.")
        if not await self._store.lock(user_id, document_id):
            raise missing
        if not await self._store.is_linked(user_id, workspace_id, document_id):
            raise missing
        document = await self._require_document(user_id, document_id)
        if document.status == "ready":
            await self._profiles.exclude(user_id, workspace_id, document_id)
        found, storage_path = await self._store.unlink(user_id, workspace_id, document_id)
        if not found:
            raise missing
        await self._store.commit()
        if document.status == "ready":
            self._summary_changed(user_id, workspace_id)
        await remove_stored_files(self._storage, [storage_path] if storage_path else [])

    async def _link_and_ingest(
        self,
        user_id: UUID,
        workspace_id: UUID,
        document: Document,
        data: bytes,
        uploaded_paths: list[str],
        *,
        override: bool,
    ) -> DocumentUploadResult:
        await self._store.link(workspace_id, document.id, override=override)
        result = DocumentUploadResult(
            document=DocumentRead.model_validate(document), duplicate=False, linked=True
        )
        try:
            await self._store.commit()
        except Exception:
            await remove_stored_files(self._storage, uploaded_paths)
            raise
        self._schedule(user_id, document.id, data)
        return result

    def _summary_changed(self, user_id: UUID, workspace_id: UUID) -> None:
        if self._schedule_summary is not None:
            self._schedule_summary(user_id, workspace_id)

    async def require_workspace(self, user_id: UUID, workspace_id: UUID) -> None:
        """NotFoundError unless the user owns the workspace (D-047)."""
        await self._require_workspace(user_id, workspace_id)

    async def _require_workspace(self, user_id: UUID, workspace_id: UUID) -> None:
        if not await self._store.workspace_owned(user_id, workspace_id):
            raise NotFoundError("Workspace not found.")

    async def _require_document(self, user_id: UUID, document_id: UUID) -> Document:
        document = await self._store.get(user_id, document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    def _require_storage(self) -> FileStorage:
        if self._storage is None:
            raise DependencyUnavailableError("Document storage is not configured.")
        return self._storage
