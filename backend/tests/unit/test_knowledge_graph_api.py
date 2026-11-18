"""Knowledge graph endpoints over HTTP with real token verification and an in-memory store."""

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_graph_runner
from app.core.config import Settings
from app.main import create_app
from app.repositories.knowledge_graph import EvidenceRow, NodeView
from app.services.knowledge_graph_jobs import KnowledgeGraphRunner
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.services.test_knowledge_graph_jobs import (
    OPTIONS,
    USER,
    WORKSPACE,
    InMemoryKGStore,
    ScriptedExtractor,
    runner,
)

JOBS_URL = f"/api/v1/workspaces/{WORKSPACE}/knowledge-graph/jobs"
GRAPH_URL = f"/api/v1/workspaces/{WORKSPACE}/knowledge-graph"


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
def store() -> InMemoryKGStore:
    return InMemoryKGStore()


def client_for(
    settings: Settings, key: SigningKey, kg_runner: KnowledgeGraphRunner
) -> Iterator[TestClient]:
    app: FastAPI = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[key]).verifier()
    app.dependency_overrides[get_knowledge_graph_runner] = lambda: kg_runner
    with TestClient(app) as client:
        yield client


@pytest.fixture
def gate() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
def api(
    settings: Settings, signing_key: SigningKey, store: InMemoryKGStore, gate: asyncio.Event
) -> Iterator[TestClient]:
    # The gate holds jobs open so a second request finds the first one active.
    yield from client_for(settings, signing_key, runner(store, ScriptedExtractor(gate=gate)))


def auth(key: SigningKey, user: UUID = USER) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user)}"}


def test_start_is_202_and_a_second_start_returns_the_same_job_with_200(
    api: TestClient, signing_key: SigningKey, store: InMemoryKGStore
) -> None:
    store.add_paper()

    first = api.post(JOBS_URL, headers=auth(signing_key))
    again = api.post(JOBS_URL, headers=auth(signing_key))

    assert first.status_code == 202
    assert first.json()["kind"] == "generate"
    assert first.json()["workspace_id"] == str(WORKSPACE)
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]


def test_start_without_ready_papers_is_409(api: TestClient, signing_key: SigningKey) -> None:
    response = api.post(JOBS_URL, headers=auth(signing_key))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_ready_documents"


def test_other_users_workspace_is_404_everywhere(
    api: TestClient, signing_key: SigningKey, store: InMemoryKGStore
) -> None:
    store.add_paper()
    job = api.post(JOBS_URL, headers=auth(signing_key)).json()
    stranger = auth(signing_key, uuid4())

    assert api.post(JOBS_URL, headers=stranger).status_code == 404
    assert api.get(GRAPH_URL, headers=stranger).status_code == 404
    assert api.get(f"{JOBS_URL}/{job['id']}", headers=stranger).status_code == 404


def test_job_and_graph_state_are_readable(
    api: TestClient, signing_key: SigningKey, store: InMemoryKGStore
) -> None:
    store.add_paper()
    job = api.post(JOBS_URL, headers=auth(signing_key)).json()

    read = api.get(f"{JOBS_URL}/{job['id']}", headers=auth(signing_key))
    graph = api.get(GRAPH_URL, headers=auth(signing_key))

    assert read.status_code == 200
    assert read.json()["id"] == job["id"]
    assert graph.status_code == 200
    body = graph.json()
    assert body["state"] in ("queued", "generating")
    assert body["active_job"]["id"] == job["id"]
    assert (body["ready_documents"], body["built_at"], body["node_count"]) == (1, None, 0)


def test_unknown_job_is_404(api: TestClient, signing_key: SigningKey) -> None:
    assert api.get(f"{JOBS_URL}/{uuid4()}", headers=auth(signing_key)).status_code == 404


def test_requires_a_token(api: TestClient) -> None:
    assert api.post(JOBS_URL).status_code == 401
    assert api.get(GRAPH_URL).status_code == 401


def test_start_is_503_until_extraction_is_configured(
    settings: Settings, signing_key: SigningKey, store: InMemoryKGStore
) -> None:
    store.add_paper()
    unconfigured = KnowledgeGraphRunner(store.open, extractor=None, builder=None, options=OPTIONS)

    for client in client_for(settings, signing_key, unconfigured):
        start = client.post(JOBS_URL, headers=auth(signing_key))
        graph = client.get(GRAPH_URL, headers=auth(signing_key))

    assert start.status_code == 503
    assert graph.status_code == 200
    assert graph.json()["state"] == "empty"


def test_without_a_database_the_endpoints_are_503(
    settings: Settings, signing_key: SigningKey
) -> None:
    app: FastAPI = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    with TestClient(app) as client:
        assert client.get(GRAPH_URL, headers=auth(signing_key)).status_code == 503


def test_graph_lists_nodes_and_evidence_opens_in_the_source_viewer_shape(
    api: TestClient, signing_key: SigningKey, store: InMemoryKGStore
) -> None:
    node = NodeView(
        id=uuid4(),
        entity_type="method",
        label="LSTM",
        aliases=["LSTMs"],
        document_count=2,
        mention_count=3,
    )
    store.nodes[WORKSPACE] = [node]
    passage = EvidenceRow(
        id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        document_title="Paper",
        page_start=3,
        page_end=3,
        section="Results",
        quote="We evaluated LSTM on M4.",
    )
    store.evidence[node.id] = [passage]

    graph = api.get(GRAPH_URL, headers=auth(signing_key)).json()
    evidence = api.get(f"{GRAPH_URL}/nodes/{node.id}/evidence", headers=auth(signing_key))

    assert graph["nodes"] == [
        {
            "id": str(node.id),
            "entity_type": "method",
            "label": "LSTM",
            "aliases": ["LSTMs"],
            "document_count": 2,
            "mention_count": 3,
        }
    ]
    assert (graph["edges"], graph["truncated"]) == ([], False)
    assert evidence.status_code == 200
    (row,) = evidence.json()
    assert row["source_type"] == "workspace"
    assert (row["chunk_id"], row["page_start"], row["quote"]) == (
        str(passage.chunk_id),
        3,
        "We evaluated LSTM on M4.",
    )


def test_evidence_of_unknown_or_foreign_nodes_and_edges_is_404(
    api: TestClient, signing_key: SigningKey
) -> None:
    node_url = f"{GRAPH_URL}/nodes/{uuid4()}/evidence"
    edge_url = f"{GRAPH_URL}/edges/{uuid4()}/evidence"

    assert api.get(node_url, headers=auth(signing_key, uuid4())).status_code == 404
    assert api.get(edge_url, headers=auth(signing_key)).status_code == 404
    assert api.get(f"{node_url}?limit=0", headers=auth(signing_key)).status_code == 422
