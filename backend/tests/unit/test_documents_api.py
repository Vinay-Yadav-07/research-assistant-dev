"""Document endpoints over HTTP with real token verification, an in-memory store, and fake Storage.

The SQL ownership filters, the unique content hash, and D-046 deletion are covered by
`tests/integration/test_documents_db.py`; the pipeline by `tests/unit/services/test_ingestion.py`.
"""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_compatibility_service, get_document_service
from app.core.config import Settings
from app.main import create_app
from app.models.document import DOCUMENT_STATUSES, Document
from app.providers.fakes import FakeEmbedder, FakeParser
from app.repositories.topic_profiles import ProfileState
from app.schemas.documents import DocumentSource, DocumentStatus
from app.services.compatibility import CompatibilityService
from app.services.documents import DocumentService, storage_path_for
from app.services.ingestion import IngestionOptions
from app.services.topic_profile import CompatibilityOptions, TopicProfileService
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.profile_fakes import InMemoryProfileStore, LinkResult
from tests.unit.storage_fakes import InMemoryFileStorage

ALICE = uuid4()
BOB = uuid4()
PDF = b"%PDF-fake\nTitle: Scaffold porosity\n# Introduction\nPorous scaffolds."
OTHER_PDF = b"%PDF-fake\n# Methods\nElectrospinning."
MAX_UPLOAD_BYTES = 4096
COMPATIBILITY = CompatibilityOptions(first_chunks=2, max_pages=3, threshold=0.5)
TOPIC_PDF = (
    b"%PDF-fake\n# Introduction\n"
    b"Porous hydrogel scaffolds improve fibroblast infiltration in tissue engineering."
)
RELATED_PDF = (
    b"%PDF-fake\n# Introduction\n"
    b"Porous hydrogel scaffolds improve cell infiltration and tissue engineering outcomes."
)
UNRELATED_PDF = (
    b"%PDF-fake\n# Abstract\nStock market prediction from trading volume with recurrent networks."
)


class InMemoryDocumentStore:
    """Mirrors `DocumentRepository`'s ownership rules without a database."""

    def __init__(self) -> None:
        self.profiles = InMemoryProfileStore()
        self.workspaces: dict[UUID, UUID] = self.profiles.workspaces
        self.documents: dict[UUID, Document] = {}
        self.links: set[tuple[UUID, UUID]] = set()
        self.commits = 0
        self.fail_commit = False
        self._tick = datetime(2026, 1, 1, tzinfo=UTC)

    def add_workspace(self, user_id: UUID) -> UUID:
        workspace_id = uuid4()
        self.workspaces[workspace_id] = user_id
        return workspace_id

    async def workspace_owned(self, user_id: UUID, workspace_id: UUID) -> bool:
        return self.workspaces.get(workspace_id) == user_id

    async def get(self, user_id: UUID, document_id: UUID) -> Document | None:
        document = self.documents.get(document_id)
        return document if document is not None and document.user_id == user_id else None

    async def find_by_hash(self, user_id: UUID, content_hash: str) -> Document | None:
        for document in self.documents.values():
            if document.user_id == user_id and document.content_hash == content_hash:
                return document
        return None

    async def create(
        self,
        user_id: UUID,
        document_id: UUID,
        *,
        content_hash: str,
        storage_path: str,
        source: DocumentSource = "upload",
        source_url: str | None = None,
    ) -> Document | None:
        if await self.find_by_hash(user_id, content_hash) is not None:
            return None
        self._tick += timedelta(seconds=1)
        document = Document(
            id=document_id,
            user_id=user_id,
            content_hash=content_hash,
            storage_path=storage_path,
            source=source,
            source_url=source_url,
            status="uploaded",
            created_at=self._tick,
            updated_at=self._tick,
        )
        self.documents[document_id] = document
        return document

    async def is_linked(self, user_id: UUID, workspace_id: UUID, document_id: UUID) -> bool:
        return (
            await self.workspace_owned(user_id, workspace_id)
            and await self.get(user_id, document_id) is not None
            and (workspace_id, document_id) in self.links
        )

    async def lock(self, user_id: UUID, document_id: UUID) -> bool:
        return await self.get(user_id, document_id) is not None

    async def link(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        compatibility_score: float | None = None,
        override: bool = False,
    ) -> None:
        if (workspace_id, document_id) not in self.links:
            self.links.add((workspace_id, document_id))
            self.profiles.links[(workspace_id, document_id)] = LinkResult(
                compatibility_score, override
            )

    async def list_in_workspace(
        self, user_id: UUID, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[Document]:
        if not await self.workspace_owned(user_id, workspace_id):
            return []
        linked = [
            document
            for document in self.documents.values()
            if (workspace_id, document.id) in self.links and document.user_id == user_id
        ]
        linked.sort(key=lambda document: document.created_at, reverse=True)
        return linked[offset : offset + limit]

    async def unlink(
        self, user_id: UUID, workspace_id: UUID, document_id: UUID
    ) -> tuple[bool, str | None]:
        if not await self.is_linked(user_id, workspace_id, document_id):
            return False, None
        self.links.discard((workspace_id, document_id))
        self.profiles.links.pop((workspace_id, document_id), None)
        if any(linked == document_id for _, linked in self.links):
            return True, None
        return True, self.documents.pop(document_id).storage_path

    async def restart(self, user_id: UUID, document_id: UUID) -> Document | None:
        document = await self.get(user_id, document_id)
        if document is None or document.status != "failed":
            return None
        document.status = "uploaded"
        document.error = None
        return document

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.commits += 1


class Scheduled:
    """Records ingestions the service schedules instead of running them."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, bytes]] = []

    def __call__(self, user_id: UUID, document_id: UUID, data: bytes) -> None:
        self.calls.append((user_id, document_id, data))


class SummaryRefreshes(list[tuple[UUID, UUID]]):
    """Records keyword summary refreshes the service schedules (D-068)."""

    def __call__(self, user_id: UUID, workspace_id: UUID) -> None:
        self.append((user_id, workspace_id))


@pytest.fixture
def summary_refreshes() -> SummaryRefreshes:
    return SummaryRefreshes()


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
def store() -> InMemoryDocumentStore:
    return InMemoryDocumentStore()


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def scheduled() -> Scheduled:
    return Scheduled()


@pytest.fixture
def auth_app(
    settings: Settings,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
    summary_refreshes: SummaryRefreshes,
) -> FastAPI:
    app = create_app(
        settings.model_copy(
            update={"supabase_url": SUPABASE_URL, "max_upload_bytes": MAX_UPLOAD_BYTES}
        )
    )
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    app.dependency_overrides[get_compatibility_service] = lambda: compatibility_service(
        store, settings
    )
    app.dependency_overrides[get_document_service] = lambda: DocumentService(
        store,
        storage,
        scheduled,
        profiles=TopicProfileService(store.profiles, COMPATIBILITY),
        signed_url_ttl_seconds=60,
        schedule_summary=summary_refreshes,
    )
    return app


def compatibility_service(
    store: InMemoryDocumentStore, settings: Settings, parser: FakeParser | None = None
) -> CompatibilityService:
    return CompatibilityService(
        store.profiles,
        parser=parser or FakeParser(),
        embedder=FakeEmbedder(dimension=384),
        options=COMPATIBILITY,
        ingestion=IngestionOptions.from_settings(settings),
    )


@pytest.fixture
def api(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as client:
        yield client


def bearer(key: SigningKey, user: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user)}"}


def upload(
    api: TestClient,
    key: SigningKey,
    user: UUID,
    workspace_id: UUID,
    data: bytes = PDF,
    filename: str = "paper.pdf",
    content_type: str = "application/pdf",
) -> Any:
    return api.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": (filename, data, content_type)},
        headers=bearer(key, user),
    )


def uploaded(
    api: TestClient, key: SigningKey, user: UUID, workspace_id: UUID, data: bytes = PDF
) -> dict[str, Any]:
    response = upload(api, key, user, workspace_id, data)
    assert response.status_code == 202, response.text
    document: dict[str, Any] = response.json()["document"]
    return document


def test_document_statuses_match_the_model() -> None:
    assert get_args(DocumentStatus) == DOCUMENT_STATUSES


# --- upload ---


def test_upload_stores_links_and_schedules_ingestion(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)

    response = upload(api, signing_key, ALICE, workspace)

    assert response.status_code == 202
    body = response.json()
    assert body["duplicate"] is False
    assert body["linked"] is True
    document = body["document"]
    assert document["status"] == "uploaded"
    assert document["source"] == "upload"
    assert document["authors"] == []
    document_id = UUID(document["id"])
    assert storage.objects == {storage_path_for(ALICE, document_id): PDF}
    assert store.documents[document_id].content_hash == hashlib.sha256(PDF).hexdigest()
    assert (workspace, document_id) in store.links
    assert scheduled.calls == [(ALICE, document_id, PDF)]
    assert store.commits == 1


def test_pdf_is_detected_by_content_not_name(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)

    response = upload(
        api, signing_key, ALICE, workspace, filename="paper.bin", content_type="text/plain"
    )

    assert response.status_code == 202


def test_pdf_header_after_leading_bytes_is_accepted(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)

    response = upload(api, signing_key, ALICE, workspace, data=b"\r\n\x00junk" + PDF)

    assert response.status_code == 202


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04 a docx with a .pdf name",
        b"x" * 1024 + b"%PDF-1.7",
        b"",
    ],
    ids=["zip", "header-too-late", "empty"],
)
def test_non_pdf_is_415_with_guidance(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
    data: bytes,
) -> None:
    workspace = store.add_workspace(ALICE)

    response = upload(api, signing_key, ALICE, workspace, data=data)

    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "unsupported_file_type"
    assert "PDF" in error["message"]
    assert storage.objects == {}
    assert store.documents == {}
    assert scheduled.calls == []


def test_upload_at_the_size_limit_is_accepted(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)
    data = PDF + b" " * (MAX_UPLOAD_BYTES - len(PDF))

    assert upload(api, signing_key, ALICE, workspace, data=data).status_code == 202


def test_upload_over_the_size_limit_is_413(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
) -> None:
    workspace = store.add_workspace(ALICE)
    data = PDF + b" " * (MAX_UPLOAD_BYTES - len(PDF) + 1)

    response = upload(api, signing_key, ALICE, workspace, data=data)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert response.json()["error"]["details"] == {"max_bytes": MAX_UPLOAD_BYTES}
    assert storage.objects == {}


def test_upload_without_a_file_is_422(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)

    response = api.post(
        f"/api/v1/workspaces/{workspace}/documents", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 422


def test_storage_failure_is_502_and_nothing_is_kept(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)
    storage.fail_uploads = True

    response = upload(api, signing_key, ALICE, workspace)

    assert response.status_code == 502
    assert store.commits == 0  # the request session rolls the row back
    assert scheduled.calls == []


def test_failed_commit_removes_the_uploaded_file(
    signing_key: SigningKey,
    auth_app: FastAPI,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)
    store.fail_commit = True

    with TestClient(auth_app, raise_server_exceptions=False) as client:
        response = upload(client, signing_key, ALICE, workspace)

    assert response.status_code == 500
    assert storage.objects == {}
    assert len(storage.deleted) == 1
    assert scheduled.calls == []


def test_upload_without_storage_is_503(
    signing_key: SigningKey, auth_app: FastAPI, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)
    auth_app.dependency_overrides[get_document_service] = lambda: DocumentService(
        store,
        None,
        Scheduled(),
        profiles=TopicProfileService(store.profiles, COMPATIBILITY),
        signed_url_ttl_seconds=60,
    )

    with TestClient(auth_app) as client:
        response = upload(client, signing_key, ALICE, workspace)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"


def test_unconfigured_database_is_503(settings: Settings, signing_key: SigningKey) -> None:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()

    with TestClient(app) as client:
        response = client.get(f"/api/v1/documents/{uuid4()}", headers=bearer(signing_key, ALICE))

    assert response.status_code == 503


# --- duplicates (SRS §20) ---


def test_duplicate_in_the_same_workspace_is_reported_linked(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)
    first = uploaded(api, signing_key, ALICE, workspace)

    response = upload(api, signing_key, ALICE, workspace, filename="renamed.pdf")

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["linked"] is True
    assert response.json()["document"]["id"] == first["id"]
    assert len(storage.objects) == 1
    assert len(scheduled.calls) == 1


def test_duplicate_from_another_workspace_offers_linking(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, scheduled: Scheduled
) -> None:
    first_workspace = store.add_workspace(ALICE)
    second_workspace = store.add_workspace(ALICE)
    first = uploaded(api, signing_key, ALICE, first_workspace)

    response = upload(api, signing_key, ALICE, second_workspace)

    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["linked"] is False
    assert (second_workspace, UUID(first["id"])) not in store.links
    assert len(scheduled.calls) == 1

    linked = api.put(
        f"/api/v1/workspaces/{second_workspace}/documents/{first['id']}",
        headers=bearer(signing_key, ALICE),
    )

    assert linked.status_code == 200
    assert linked.json()["id"] == first["id"]
    assert (second_workspace, UUID(first["id"])) in store.links
    again = upload(api, signing_key, ALICE, second_workspace)
    assert again.json()["linked"] is True


def test_linking_is_idempotent(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, workspace)
    url = f"/api/v1/workspaces/{workspace}/documents/{document['id']}"

    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200
    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200
    assert store.links == {(workspace, UUID(document["id"]))}


def test_failed_duplicate_is_ingested_again(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, workspace)
    stored = store.documents[UUID(document["id"])]
    stored.status = "failed"
    stored.error = "The file is not a readable PDF."

    response = upload(api, signing_key, ALICE, workspace)

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert response.json()["document"]["id"] == document["id"]
    assert response.json()["document"]["status"] == "uploaded"
    assert response.json()["document"]["error"] is None
    assert len(scheduled.calls) == 2
    assert len(storage.objects) == 1


def test_the_same_file_from_two_users_is_two_documents(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    alice_document = uploaded(api, signing_key, ALICE, store.add_workspace(ALICE))
    bob_document = uploaded(api, signing_key, BOB, store.add_workspace(BOB))

    assert alice_document["id"] != bob_document["id"]


# --- read, download, remove ---


def test_list_and_get(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)
    first = uploaded(api, signing_key, ALICE, workspace)
    second = uploaded(api, signing_key, ALICE, workspace, data=OTHER_PDF)
    headers = bearer(signing_key, ALICE)

    listed = api.get(f"/api/v1/workspaces/{workspace}/documents", headers=headers)
    page = api.get(f"/api/v1/workspaces/{workspace}/documents?limit=1&offset=1", headers=headers)
    fetched = api.get(f"/api/v1/documents/{first['id']}", headers=headers)

    assert [d["id"] for d in listed.json()] == [second["id"], first["id"]]
    assert [d["id"] for d in page.json()] == [first["id"]]
    assert fetched.json() == first


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_rejects_bad_paging(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, query: str
) -> None:
    workspace = store.add_workspace(ALICE)

    response = api.get(
        f"/api/v1/workspaces/{workspace}/documents?{query}", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 422


def test_file_returns_a_signed_url(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, workspace)

    response = api.get(
        f"/api/v1/documents/{document['id']}/file", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith(f"https://storage.test/sign/{ALICE}/{document['id']}.pdf")
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(0) < expires_at - datetime.now(UTC) <= timedelta(seconds=60)


def test_remove_last_link_deletes_document_and_file(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
) -> None:
    workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, workspace)
    headers = bearer(signing_key, ALICE)

    response = api.delete(
        f"/api/v1/workspaces/{workspace}/documents/{document['id']}", headers=headers
    )

    assert response.status_code == 204
    assert api.get(f"/api/v1/documents/{document['id']}", headers=headers).status_code == 404
    assert storage.deleted == [[f"{ALICE}/{document['id']}.pdf"]]
    assert storage.objects == {}


def test_remove_shared_document_only_unlinks(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
) -> None:
    first_workspace = store.add_workspace(ALICE)
    second_workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, first_workspace)
    headers = bearer(signing_key, ALICE)
    api.put(f"/api/v1/workspaces/{second_workspace}/documents/{document['id']}", headers=headers)

    response = api.delete(
        f"/api/v1/workspaces/{first_workspace}/documents/{document['id']}", headers=headers
    )

    assert response.status_code == 204
    assert api.get(f"/api/v1/documents/{document['id']}", headers=headers).status_code == 200
    assert storage.deleted == []
    listed = api.get(f"/api/v1/workspaces/{first_workspace}/documents", headers=headers)
    assert listed.json() == []


def test_remove_survives_a_storage_failure(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, workspace)

    async def broken_delete(paths: list[str]) -> None:
        raise RuntimeError("storage down")

    monkeypatch.setattr(storage, "delete", broken_delete)

    response = api.delete(
        f"/api/v1/workspaces/{workspace}/documents/{document['id']}",
        headers=bearer(signing_key, ALICE),
    )

    assert response.status_code == 204
    assert UUID(document["id"]) not in store.documents


def test_remove_unlinked_document_is_404(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    first_workspace = store.add_workspace(ALICE)
    second_workspace = store.add_workspace(ALICE)
    document = uploaded(api, signing_key, ALICE, first_workspace)

    response = api.delete(
        f"/api/v1/workspaces/{second_workspace}/documents/{document['id']}",
        headers=bearer(signing_key, ALICE),
    )

    assert response.status_code == 404
    assert UUID(document["id"]) in store.documents


# --- cross-user isolation (D-047) ---


@pytest.fixture
def alice_document(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> tuple[UUID, str]:
    workspace = store.add_workspace(ALICE)
    return workspace, uploaded(api, signing_key, ALICE, workspace)["id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/workspaces/{workspace}/documents"),
        ("PUT", "/api/v1/workspaces/{workspace}/documents/{document}"),
        ("DELETE", "/api/v1/workspaces/{workspace}/documents/{document}"),
        ("GET", "/api/v1/documents/{document}"),
        ("GET", "/api/v1/documents/{document}/file"),
    ],
)
def test_other_users_documents_are_404(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    alice_document: tuple[UUID, str],
    method: str,
    path: str,
) -> None:
    workspace, document = alice_document
    url = path.format(workspace=workspace, document=document)

    response = api.request(method, url, headers=bearer(signing_key, BOB))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert (workspace, UUID(document)) in store.links


def test_upload_into_another_users_workspace_is_404(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    scheduled: Scheduled,
) -> None:
    workspace = store.add_workspace(ALICE)

    response = upload(api, signing_key, BOB, workspace)

    assert response.status_code == 404
    assert storage.objects == {}
    assert scheduled.calls == []


def test_linking_another_users_document_is_404(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    alice_document: tuple[UUID, str],
) -> None:
    bob_workspace = store.add_workspace(BOB)
    _, document = alice_document

    response = api.put(
        f"/api/v1/workspaces/{bob_workspace}/documents/{document}",
        headers=bearer(signing_key, BOB),
    )

    assert response.status_code == 404
    assert (bob_workspace, UUID(document)) not in store.links


def test_duplicate_detection_is_per_user(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    alice_document: tuple[UUID, str],
) -> None:
    response = upload(api, signing_key, BOB, store.add_workspace(BOB))

    assert response.status_code == 202
    assert response.json()["document"]["id"] != alice_document[1]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/workspaces/{workspace}/documents"),
        ("POST", "/api/v1/workspaces/{workspace}/documents/compatibility"),
        ("GET", "/api/v1/workspaces/{workspace}/documents"),
        ("PUT", "/api/v1/workspaces/{workspace}/documents/{document}"),
        ("DELETE", "/api/v1/workspaces/{workspace}/documents/{document}"),
        ("GET", "/api/v1/documents/{document}"),
        ("GET", "/api/v1/documents/{document}/file"),
    ],
)
def test_every_document_endpoint_needs_a_token(api: TestClient, method: str, path: str) -> None:
    response = api.request(method, path.format(workspace=uuid4(), document=uuid4()))

    assert response.status_code == 401


# --- compatibility (FR-22, SRS §11.2) ---


def topic_vector(store: InMemoryDocumentStore, settings: Settings, pdf: bytes) -> list[float]:
    """The vector the compatibility check forms for `pdf`."""
    return asyncio.run(compatibility_service(store, settings).document_vector(pdf))


def with_topic(store: InMemoryDocumentStore, settings: Settings, user: UUID) -> UUID:
    """A workspace whose centroid is TOPIC_PDF's vector."""
    workspace = store.add_workspace(user)
    store.profiles.profiles[workspace] = ProfileState(
        centroid=topic_vector(store, settings, TOPIC_PDF), document_count=1
    )
    return workspace


def ready(
    api: TestClient,
    key: SigningKey,
    store: InMemoryDocumentStore,
    settings: Settings,
    workspace: UUID,
    pdf: bytes,
) -> UUID:
    """Upload `pdf` and mark it ready with its chunk vector stored."""
    document_id = UUID(uploaded(api, key, ALICE, workspace, pdf)["id"])
    store.documents[document_id].status = "ready"
    store.profiles.chunks[document_id] = (ALICE, [topic_vector(store, settings, pdf)])
    return document_id


def check(api: TestClient, key: SigningKey, user: UUID, workspace: UUID, pdf: bytes) -> Any:
    return api.post(
        f"/api/v1/workspaces/{workspace}/documents/compatibility",
        files={"file": ("paper.pdf", pdf, "application/pdf")},
        headers=bearer(key, user),
    )


def test_check_skips_an_empty_workspace_without_parsing(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)

    # The fake parser rejects real PDFs, so a 200 shows nothing was parsed.
    response = check(api, signing_key, ALICE, workspace, b"%PDF-1.7 real bytes")

    assert response.status_code == 200
    assert response.json() == {
        "score": None,
        "threshold": 0.5,
        "compatible": True,
        "skipped": True,
    }


def test_check_accepts_a_related_document(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    workspace = with_topic(store, settings, ALICE)

    response = check(api, signing_key, ALICE, workspace, RELATED_PDF)

    assert response.status_code == 200
    body = response.json()
    assert body["compatible"] is True
    assert body["skipped"] is False
    assert body["score"] >= 0.5


def test_check_warns_about_an_unrelated_document_and_stores_nothing(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    storage: InMemoryFileStorage,
    settings: Settings,
) -> None:
    workspace = with_topic(store, settings, ALICE)
    before = store.profiles.profiles[workspace]

    response = check(api, signing_key, ALICE, workspace, UNRELATED_PDF)

    assert response.status_code == 200
    assert response.json()["compatible"] is False
    assert response.json()["score"] < 0.5
    assert store.profiles.profiles[workspace] == before
    assert store.documents == {}
    assert storage.objects == {}


def test_check_reads_only_the_first_pages(
    auth_app: FastAPI, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    pages_read: list[int | None] = []

    class RecordingParser(FakeParser):
        async def parse(self, data: bytes, *, max_pages: int | None = None) -> Any:
            pages_read.append(max_pages)
            return await super().parse(data, max_pages=max_pages)

    workspace = with_topic(store, settings, ALICE)
    auth_app.dependency_overrides[get_compatibility_service] = lambda: compatibility_service(
        store, settings, RecordingParser()
    )
    # Page 4 is unrelated but never read.
    pdf = RELATED_PDF + b"\f\f\f" + UNRELATED_PDF.removeprefix(b"%PDF-fake\n") * 50

    with TestClient(auth_app) as client:
        response = check(client, signing_key, ALICE, workspace, pdf)

    assert pages_read == [COMPATIBILITY.max_pages]
    assert response.json()["compatible"] is True


def test_check_rejects_non_pdf(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    workspace = with_topic(store, settings, ALICE)

    response = check(api, signing_key, ALICE, workspace, b"plain text")

    assert response.status_code == 415


def test_check_on_another_users_or_a_missing_workspace_is_404(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    workspace = with_topic(store, settings, ALICE)

    for target in (workspace, uuid4()):
        response = check(api, signing_key, BOB, target, RELATED_PDF)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_upload_records_override(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore
) -> None:
    workspace = store.add_workspace(ALICE)

    response = api.post(
        f"/api/v1/workspaces/{workspace}/documents",
        files={"file": ("paper.pdf", UNRELATED_PDF, "application/pdf")},
        data={"override": "true"},
        headers=bearer(signing_key, ALICE),
    )

    assert response.status_code == 202
    document_id = UUID(response.json()["document"]["id"])
    assert store.profiles.links[(workspace, document_id)] == LinkResult(None, override=True)


def test_linking_an_unrelated_ready_document_warns(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, UNRELATED_PDF)
    target = with_topic(store, settings, ALICE)
    url = f"/api/v1/workspaces/{target}/documents/{document_id}"

    response = api.put(url, headers=bearer(signing_key, ALICE))

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "compatibility_warning"
    assert error["details"]["score"] < 0.5
    assert error["details"]["threshold"] == 0.5
    assert (target, document_id) not in store.links
    assert store.profiles.profiles[target].document_count == 1

    response = api.put(url, params={"override": "true"}, headers=bearer(signing_key, ALICE))

    assert response.status_code == 200
    link = store.profiles.links[(target, document_id)]
    assert link.override is True
    assert link.score is not None and link.score < 0.5
    assert store.profiles.profiles[target].document_count == 2


def test_linking_a_related_ready_document_records_its_score(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, RELATED_PDF)
    target = with_topic(store, settings, ALICE)

    response = api.put(
        f"/api/v1/workspaces/{target}/documents/{document_id}", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 200
    link = store.profiles.links[(target, document_id)]
    assert link.score is not None and link.score >= 0.5
    assert link.override is False
    assert store.profiles.profiles[target].document_count == 2


def test_linking_into_an_empty_workspace_starts_its_profile(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, UNRELATED_PDF)
    target = store.add_workspace(ALICE)

    response = api.put(
        f"/api/v1/workspaces/{target}/documents/{document_id}", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 200
    assert store.profiles.links[(target, document_id)] == LinkResult(None, override=False)
    assert store.profiles.profiles[target].document_count == 1


def test_linking_a_document_still_ingesting_defers_the_score(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = UUID(uploaded(api, signing_key, ALICE, source, UNRELATED_PDF)["id"])
    target = with_topic(store, settings, ALICE)

    response = api.put(
        f"/api/v1/workspaces/{target}/documents/{document_id}", headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 200
    assert store.profiles.links[(target, document_id)] == LinkResult(None, override=False)
    assert store.profiles.profiles[target].document_count == 1


def test_relinking_does_not_count_the_document_twice(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, RELATED_PDF)
    target = with_topic(store, settings, ALICE)
    url = f"/api/v1/workspaces/{target}/documents/{document_id}"

    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200
    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200

    assert store.profiles.profiles[target].document_count == 2


def test_removing_a_ready_document_takes_it_out_of_the_profile(
    api: TestClient, signing_key: SigningKey, store: InMemoryDocumentStore, settings: Settings
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, RELATED_PDF)
    target = with_topic(store, settings, ALICE)
    url = f"/api/v1/workspaces/{target}/documents/{document_id}"
    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200

    assert api.delete(url, headers=bearer(signing_key, ALICE)).status_code == 204

    profile = store.profiles.profiles[target]
    assert profile.document_count == 1
    expected = topic_vector(store, settings, TOPIC_PDF)
    assert profile.centroid == pytest.approx(expected)


# --- Keyword summary refresh (S7, D-068) ---


def test_linking_a_ready_document_refreshes_the_summary_once(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    settings: Settings,
    summary_refreshes: SummaryRefreshes,
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, RELATED_PDF)
    target = with_topic(store, settings, ALICE)
    url = f"/api/v1/workspaces/{target}/documents/{document_id}"

    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200
    assert api.put(url, headers=bearer(signing_key, ALICE)).status_code == 200

    assert summary_refreshes == [(ALICE, target)]


def test_refused_or_deferred_links_refresh_no_summary(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    settings: Settings,
    summary_refreshes: SummaryRefreshes,
) -> None:
    source = store.add_workspace(ALICE)
    unrelated = ready(api, signing_key, store, settings, source, UNRELATED_PDF)
    ingesting = UUID(uploaded(api, signing_key, ALICE, source, RELATED_PDF)["id"])
    target = with_topic(store, settings, ALICE)

    refused = api.put(
        f"/api/v1/workspaces/{target}/documents/{unrelated}", headers=bearer(signing_key, ALICE)
    )
    deferred = api.put(
        f"/api/v1/workspaces/{target}/documents/{ingesting}", headers=bearer(signing_key, ALICE)
    )

    assert (refused.status_code, deferred.status_code) == (409, 200)
    # The deferred document's workspaces are refreshed when ingestion makes it ready.
    assert summary_refreshes == []


def test_removing_a_ready_document_refreshes_the_summary(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryDocumentStore,
    settings: Settings,
    summary_refreshes: SummaryRefreshes,
) -> None:
    source = store.add_workspace(ALICE)
    document_id = ready(api, signing_key, store, settings, source, RELATED_PDF)
    url = f"/api/v1/workspaces/{source}/documents/{document_id}"

    assert api.delete(url, headers=bearer(signing_key, ALICE)).status_code == 204

    assert summary_refreshes == [(ALICE, source)]
