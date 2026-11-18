"""Workspace endpoints over HTTP with real token verification and an in-memory store.

The SQL ownership filters and D-046 document deletion are covered by
`tests/integration/test_workspaces_db.py`.
"""

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_workspace_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models.topic_profile import TopicProfile
from app.models.workspace import KNOWLEDGE_MODES, Workspace
from app.schemas.workspaces import KnowledgeMode
from app.services.workspaces import WorkspaceService
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.storage_fakes import InMemoryFileStorage

ALICE = uuid4()
BOB = uuid4()


class InMemoryWorkspaceStore:
    """Mirrors `WorkspaceRepository`'s ownership rules without a database."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Workspace] = {}
        self.commits = 0
        self._tick = datetime(2026, 1, 1, tzinfo=UTC)

    def _now(self) -> datetime:
        self._tick += timedelta(seconds=1)
        return self._tick

    async def list_owned(self, user_id: UUID, *, limit: int, offset: int) -> list[Workspace]:
        owned = [row for row in self.rows.values() if row.user_id == user_id]
        owned.sort(key=lambda row: row.created_at, reverse=True)
        return owned[offset : offset + limit]

    async def get(self, user_id: UUID, workspace_id: UUID) -> Workspace | None:
        row = self.rows.get(workspace_id)
        return row if row is not None and row.user_id == user_id else None

    async def create(
        self, user_id: UUID, *, name: str, description: str | None, default_mode: str
    ) -> Workspace:
        now = self._now()
        row = Workspace(
            id=uuid4(),
            user_id=user_id,
            name=name,
            description=description,
            default_mode=default_mode,
            archived=False,
            created_at=now,
            updated_at=now,
        )
        self.rows[row.id] = row
        return row

    async def update(
        self, user_id: UUID, workspace_id: UUID, changes: dict[str, object]
    ) -> Workspace | None:
        row = await self.get(user_id, workspace_id)
        if row is not None and changes:
            for field, value in changes.items():
                setattr(row, field, value)
            row.updated_at = self._now()
        return row

    async def delete(self, user_id: UUID, workspace_id: UUID) -> list[str] | None:
        if await self.get(user_id, workspace_id) is None:
            return None
        del self.rows[workspace_id]
        return []

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
def store() -> InMemoryWorkspaceStore:
    return InMemoryWorkspaceStore()


@pytest.fixture
def auth_app(settings: Settings, signing_key: SigningKey, store: InMemoryWorkspaceStore) -> FastAPI:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    app.dependency_overrides[get_workspace_service] = lambda: WorkspaceService(store)
    return app


@pytest.fixture
def api(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as client:
        yield client


def bearer(key: SigningKey, user: UUID, **claims: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user, **claims)}"}


def create(api: TestClient, key: SigningKey, user: UUID, **body: Any) -> dict[str, Any]:
    response = api.post(
        "/api/v1/workspaces", json={"name": "Scaffolds", **body}, headers=bearer(key, user)
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


# --- authentication ---


def test_missing_token_is_401(api: TestClient) -> None:
    response = api.get("/api/v1/workspaces")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(
    "claims",
    [{"exp": int(time.time()) - 3600}, {"iss": "https://evil.supabase.co/auth/v1"}],
    ids=["expired", "wrong-issuer"],
)
def test_invalid_token_is_401(
    api: TestClient, signing_key: SigningKey, claims: dict[str, Any]
) -> None:
    response = api.get("/api/v1/workspaces", headers=bearer(signing_key, ALICE, **claims))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_non_bearer_scheme_is_401(api: TestClient, signing_key: SigningKey) -> None:
    token = issue(signing_key, ALICE)

    response = api.get("/api/v1/workspaces", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 401


def test_rejected_token_is_never_logged(
    api: TestClient, signing_key: SigningKey, caplog: pytest.LogCaptureFixture
) -> None:
    token = issue(signing_key, ALICE, exp=int(time.time()) - 3600)
    caplog.set_level(logging.DEBUG)

    response = api.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "Access token rejected: ExpiredSignatureError" in caplog.text
    for part in token.split("."):
        assert part not in caplog.text


def test_unconfigured_auth_is_503(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer x"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"


def test_prod_without_supabase_url_fails_at_startup(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ENVIRONMENT", "prod")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="SUPABASE_URL is required"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_health_needs_no_token(api: TestClient) -> None:
    assert api.get("/api/v1/health").status_code == 200


# --- CRUD ---


def test_create_and_get(api: TestClient, signing_key: SigningKey) -> None:
    created = create(api, signing_key, ALICE, name="  Scaffolds  ", description="Bone tissue")

    assert created["name"] == "Scaffolds"
    assert created["description"] == "Bone tissue"
    assert created["default_mode"] == "corpus_only"
    assert created["archived"] is False
    assert (created["keywords"], created["summary"]) == (None, None)
    fetched = api.get(f"/api/v1/workspaces/{created['id']}", headers=bearer(signing_key, ALICE))
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_list_is_newest_first_and_paged(api: TestClient, signing_key: SigningKey) -> None:
    names = [create(api, signing_key, ALICE, name=f"W{i}")["name"] for i in range(3)]
    headers = bearer(signing_key, ALICE)

    everything = api.get("/api/v1/workspaces", headers=headers).json()
    page = api.get("/api/v1/workspaces?limit=1&offset=1", headers=headers).json()

    assert [w["name"] for w in everything] == names[::-1]
    assert [w["name"] for w in page] == [names[1]]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_list_rejects_bad_paging(api: TestClient, signing_key: SigningKey, query: str) -> None:
    response = api.get(f"/api/v1/workspaces?{query}", headers=bearer(signing_key, ALICE))

    assert response.status_code == 422


def test_list_accepts_max_page_size(api: TestClient, signing_key: SigningKey) -> None:
    response = api.get("/api/v1/workspaces?limit=100", headers=bearer(signing_key, ALICE))

    assert response.status_code == 200


def test_patch_renames_and_archives_and_restores(api: TestClient, signing_key: SigningKey) -> None:
    workspace = create(api, signing_key, ALICE, description="old")
    url = f"/api/v1/workspaces/{workspace['id']}"
    headers = bearer(signing_key, ALICE)

    renamed = api.patch(url, json={"name": "Hydrogels", "description": None}, headers=headers)
    archived = api.patch(url, json={"archived": True}, headers=headers)
    restored = api.patch(url, json={"archived": False}, headers=headers)

    assert renamed.json()["name"] == "Hydrogels"
    assert renamed.json()["description"] is None
    assert archived.json()["archived"] is True
    assert archived.json()["name"] == "Hydrogels"
    assert restored.json()["archived"] is False


def test_archived_workspaces_are_still_listed(api: TestClient, signing_key: SigningKey) -> None:
    workspace = create(api, signing_key, ALICE)
    headers = bearer(signing_key, ALICE)
    api.patch(f"/api/v1/workspaces/{workspace['id']}", json={"archived": True}, headers=headers)

    listed = api.get("/api/v1/workspaces", headers=headers).json()

    assert [w["archived"] for w in listed] == [True]


def test_delete_removes_workspace(
    api: TestClient, signing_key: SigningKey, store: InMemoryWorkspaceStore
) -> None:
    workspace = create(api, signing_key, ALICE)
    url = f"/api/v1/workspaces/{workspace['id']}"
    headers = bearer(signing_key, ALICE)

    response = api.delete(url, headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    assert api.get(url, headers=headers).status_code == 404
    assert store.commits == 2  # create + delete


async def test_delete_removes_stored_files_after_commit() -> None:
    class StoreWithFiles(InMemoryWorkspaceStore):
        async def delete(self, user_id: UUID, workspace_id: UUID) -> list[str] | None:
            removed = await super().delete(user_id, workspace_id)
            return None if removed is None else ["u/1.pdf", "u/2.pdf"]

    store = StoreWithFiles()
    storage = InMemoryFileStorage()
    service = WorkspaceService(store, storage)
    workspace = await store.create(ALICE, name="W", description=None, default_mode="corpus_only")

    await service.delete(ALICE, workspace.id)

    assert store.commits == 1
    assert storage.deleted == [["u/1.pdf", "u/2.pdf"]]


def test_missing_workspace_is_404(api: TestClient, signing_key: SigningKey) -> None:
    response = api.get(f"/api/v1/workspaces/{uuid4()}", headers=bearer(signing_key, ALICE))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- cross-user isolation (D-047) ---


@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("GET", None),
        ("PATCH", {"name": "Taken over"}),
        ("PATCH", {"archived": True}),
        ("DELETE", None),
    ],
)
def test_other_users_workspace_is_404(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryWorkspaceStore,
    method: str,
    body: dict[str, Any] | None,
) -> None:
    workspace = create(api, signing_key, ALICE)
    missing = api.request(
        method, f"/api/v1/workspaces/{uuid4()}", json=body, headers=bearer(signing_key, BOB)
    )

    response = api.request(
        method, f"/api/v1/workspaces/{workspace['id']}", json=body, headers=bearer(signing_key, BOB)
    )

    assert response.status_code == 404
    assert response.json() == missing.json()  # indistinguishable from a missing workspace
    row = store.rows[UUID(workspace["id"])]
    assert (row.name, row.archived) == ("Scaffolds", False)


def test_list_shows_only_own_workspaces(api: TestClient, signing_key: SigningKey) -> None:
    create(api, signing_key, ALICE, name="Alice's")
    create(api, signing_key, BOB, name="Bob's")

    listed = api.get("/api/v1/workspaces", headers=bearer(signing_key, BOB)).json()

    assert [w["name"] for w in listed] == ["Bob's"]


# --- validation ---


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"name": None},
        {"name": "ok", "description": "x" * 2001},
        {"name": "ok", "default_mode": "web_only"},
        {"name": "ok", "user_id": str(BOB)},
    ],
    ids=[
        "no-name",
        "empty",
        "blank",
        "long-name",
        "null-name",
        "long-description",
        "bad-mode",
        "extra",
    ],
)
def test_create_rejects_invalid_body(
    api: TestClient, signing_key: SigningKey, body: dict[str, Any]
) -> None:
    response = api.post("/api/v1/workspaces", json=body, headers=bearer(signing_key, ALICE))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_create_accepts_limits(api: TestClient, signing_key: SigningKey) -> None:
    created = create(
        api, signing_key, ALICE, name="x" * 120, description="d" * 2000, default_mode="corpus_web"
    )

    assert len(created["name"]) == 120
    assert created["default_mode"] == "corpus_web"


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": None},
        {"name": "x" * 121},
        {"description": "x" * 2001},
        {"default_mode": None},
        {"default_mode": "web_only"},
        {"archived": None},
        {"user_id": str(BOB)},
    ],
)
def test_patch_rejects_invalid_body(
    api: TestClient, signing_key: SigningKey, body: dict[str, Any]
) -> None:
    workspace = create(api, signing_key, ALICE)

    response = api.patch(
        f"/api/v1/workspaces/{workspace['id']}", json=body, headers=bearer(signing_key, ALICE)
    )

    assert response.status_code == 422


def test_invalid_workspace_id_is_422(api: TestClient, signing_key: SigningKey) -> None:
    response = api.get("/api/v1/workspaces/not-a-uuid", headers=bearer(signing_key, ALICE))

    assert response.status_code == 422


def test_knowledge_modes_match_the_model() -> None:
    assert set(get_args(KnowledgeMode)) == set(KNOWLEDGE_MODES)


def test_workspace_shows_its_keyword_summary(
    api: TestClient, signing_key: SigningKey, store: InMemoryWorkspaceStore
) -> None:
    created = create(api, signing_key, ALICE, name="Scaffolds")
    row = store.rows[UUID(created["id"])]
    row.topic_profile = TopicProfile(
        keywords=["scaffolds", "porosity"], summary="Porous scaffolds for bone repair."
    )

    fetched = api.get(f"/api/v1/workspaces/{created['id']}", headers=bearer(signing_key, ALICE))
    listed = api.get("/api/v1/workspaces", headers=bearer(signing_key, ALICE))

    assert fetched.json()["keywords"] == ["scaffolds", "porosity"]
    assert fetched.json()["summary"] == "Porous scaffolds for bone repair."
    assert listed.json()[0]["keywords"] == ["scaffolds", "porosity"]
