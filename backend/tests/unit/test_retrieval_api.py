"""Retrieval debug endpoint over HTTP with real token verification and an in-memory store."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_retrieval_service
from app.core.config import Settings
from app.main import create_app
from app.providers.fakes import FakeReranker
from app.services.retrieval import RetrievalService
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.services.test_retrieval import (
    EMBEDDER,
    USER,
    WORKSPACE,
    InMemoryChunkStore,
    options,
)

BOB = uuid4()
URL = f"/api/v1/workspaces/{WORKSPACE}/retrieval/debug"


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
def store() -> InMemoryChunkStore:
    return InMemoryChunkStore()


@pytest.fixture
def auth_app(settings: Settings, signing_key: SigningKey, store: InMemoryChunkStore) -> FastAPI:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    app.dependency_overrides[get_retrieval_service] = lambda: RetrievalService(
        store, embedder=EMBEDDER, reranker=FakeReranker(), options=options()
    )
    return app


@pytest.fixture
def api(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as client:
        yield client


def bearer(key: SigningKey, user: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user)}"}


def post(api: TestClient, key: SigningKey, user: UUID, body: dict[str, Any]) -> Any:
    return api.post(URL, json=body, headers=bearer(key, user))


async def test_debug_returns_evidence_candidates_and_timings(
    api: TestClient, signing_key: SigningKey, store: InMemoryChunkStore
) -> None:
    relevant = await store.add("Scaffold porosity improved fibroblast infiltration.", page=3)
    await store.add("Cardiac patches were bioprinted.")

    response = post(api, signing_key, USER, {"query": "scaffold porosity", "top_k": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "scaffold porosity"
    [top] = body["evidence"]
    assert top["chunk_id"] == str(relevant)
    assert (top["page_start"], top["section"]) == (3, "Results")
    assert {"dense_rank", "lexical_rank", "rrf_score", "rerank_score"} <= top.keys()
    assert len(body["candidates"]) == 2
    assert set(body["timings"]) == {"embed_ms", "dense_ms", "lexical_ms", "rerank_ms", "total_ms"}
    assert body["embedding_model"] == EMBEDDER.model_name


def test_needs_a_token(api: TestClient) -> None:
    assert api.post(URL, json={"query": "x"}).status_code == 401


def test_other_users_workspace_is_404(api: TestClient, signing_key: SigningKey) -> None:
    response = post(api, signing_key, BOB, {"query": "porosity"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"query": "  "},
        {"query": "x" * 201},
        {"query": "x", "top_k": 0},
        {"query": "x", "top_k": 51},
        {"query": "x", "extra": 1},
        {},
    ],
    ids=["blank", "too-long", "top-k-0", "top-k-51", "extra-field", "missing-query"],
)
def test_invalid_requests_are_422(
    api: TestClient, signing_key: SigningKey, body: dict[str, Any]
) -> None:
    assert post(api, signing_key, USER, body).status_code == 422


def test_unconfigured_database_is_503(settings: Settings, signing_key: SigningKey) -> None:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()

    with TestClient(app) as client:
        response = client.post(URL, json={"query": "x"}, headers=bearer(signing_key, USER))

    assert response.status_code == 503
