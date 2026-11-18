"""Chat history endpoints over HTTP with real token verification and an in-memory store.

The SQL ownership filters, cascades, citation snapshots, and the one-transaction answer save are
covered by `tests/integration/test_conversations_db.py`.
"""

from collections.abc import Iterator
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_conversation_service
from app.core.config import Settings
from app.main import create_app
from app.models.agent_run import RUN_STATUSES
from app.models.conversation import (
    CITATION_SOURCE_TYPES,
    CLAIM_STATUSES,
    MESSAGE_MODES,
    MESSAGE_ROLES,
    Citation,
    Claim,
    Evidence,
    Message,
)
from app.schemas.conversations import (
    CitationSourceType,
    ClaimStatus,
    MessageMode,
    MessageRole,
    RunStatus,
)
from app.services.conversations import AnswerDraft, ConversationService, RunSummary
from tests.unit.conversation_fakes import InMemoryConversationStore
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue

ALICE = uuid4()
BOB = uuid4()


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


@pytest.fixture
def api(
    settings: Settings, signing_key: SigningKey, store: InMemoryConversationStore
) -> Iterator[TestClient]:
    app: FastAPI = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    app.dependency_overrides[get_conversation_service] = lambda: ConversationService(store)
    with TestClient(app) as client:
        yield client


def bearer(key: SigningKey, user: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user)}"}


def start(
    api: TestClient, key: SigningKey, user: UUID, workspace_id: UUID, **body: Any
) -> dict[str, Any]:
    response = api.post(
        f"/api/v1/workspaces/{workspace_id}/conversations", json=body, headers=bearer(key, user)
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def answer_with_claim(conversation_id: UUID) -> Message:
    return Message(
        conversation_id=conversation_id,
        role="assistant",
        content="Porosity improves cell infiltration [1].",
        mode="corpus_only",
        claims=[
            Claim(
                position=1,
                text="Second claim",
                status="uncertain",
                evidence=[],
                citations=[],
            ),
            Claim(
                position=0,
                text="Porosity improves cell infiltration.",
                status="supported",
                support_score=0.93,
                evidence=[Evidence(chunk_id=uuid4(), score=0.93)],
                citations=[
                    Citation(
                        source_type="workspace",
                        document_id=uuid4(),
                        chunk_id=uuid4(),
                        document_title="Scaffold porosity",
                        page_start=3,
                        page_end=4,
                        section="Results",
                        quote="higher porosity increased infiltration",
                    )
                ],
            ),
        ],
    )


# --- conversations ---


def test_create_defaults_to_the_workspace_mode_and_logs_no_approval(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE)

    created = start(api, signing_key, ALICE, workspace.id, title="  Porosity  ")

    assert created["title"] == "Porosity"
    assert created["mode"] == "corpus_only"
    assert created["workspace_id"] == str(workspace.id)
    assert store.approvals == []
    assert store.commits == 1


@pytest.mark.parametrize("explicit", [True, False], ids=["chosen", "workspace-default"])
def test_corpus_web_conversation_is_logged_as_an_approval(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore, explicit: bool
) -> None:
    workspace = store.add_workspace(ALICE, "corpus_only" if explicit else "corpus_web")
    body = {"mode": "corpus_web"} if explicit else {}

    created = start(api, signing_key, ALICE, workspace.id, **body)

    assert created["mode"] == "corpus_web"
    [approval] = store.approvals
    assert approval.conversation_id == UUID(created["id"])
    assert approval.user_id == ALICE
    assert approval.run_id is None
    assert approval.decision == "corpus_web"
    assert approval.decided_at is not None


def test_explicit_corpus_only_overrides_a_corpus_web_default(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE, "corpus_web")

    created = start(api, signing_key, ALICE, workspace.id, mode="corpus_only")

    assert created["mode"] == "corpus_only"
    assert store.approvals == []


@pytest.mark.parametrize(
    "body",
    [{"mode": "general_knowledge"}, {"title": "   "}, {"title": "x" * 201}, {"extra": 1}],
    ids=["general-knowledge-mode", "blank-title", "long-title", "unknown-field"],
)
def test_invalid_create_is_422(
    api: TestClient,
    signing_key: SigningKey,
    store: InMemoryConversationStore,
    body: dict[str, Any],
) -> None:
    workspace = store.add_workspace(ALICE)

    response = api.post(
        f"/api/v1/workspaces/{workspace.id}/conversations",
        json=body,
        headers=bearer(signing_key, ALICE),
    )

    assert response.status_code == 422
    assert store.conversations == {}


def test_list_is_most_recently_active_first_and_paged(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE)
    other = store.add_workspace(ALICE)
    ids = [start(api, signing_key, ALICE, workspace.id, title=t)["id"] for t in "abc"]
    start(api, signing_key, ALICE, other.id, title="elsewhere")
    url = f"/api/v1/workspaces/{workspace.id}/conversations"

    everything = api.get(url, headers=bearer(signing_key, ALICE)).json()
    page = api.get(f"{url}?limit=1&offset=1", headers=bearer(signing_key, ALICE)).json()

    assert [c["id"] for c in everything] == ids[::-1]
    assert [c["id"] for c in page] == [ids[1]]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_out_of_range_paging_is_422(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore, query: str
) -> None:
    workspace = store.add_workspace(ALICE)
    conversation = start(api, signing_key, ALICE, workspace.id)

    for url in (
        f"/api/v1/workspaces/{workspace.id}/conversations?{query}",
        f"/api/v1/conversations/{conversation['id']}/messages?{query}",
    ):
        assert api.get(url, headers=bearer(signing_key, ALICE)).status_code == 422


def test_missing_token_is_401(api: TestClient) -> None:
    for url in (
        f"/api/v1/workspaces/{uuid4()}/conversations",
        f"/api/v1/conversations/{uuid4()}/messages",
        f"/api/v1/messages/{uuid4()}/claims",
    ):
        assert api.get(url).status_code == 401


# --- messages and claims ---


async def test_messages_are_listed_oldest_first_and_paged(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE)
    conversation_id = UUID(start(api, signing_key, ALICE, workspace.id)["id"])
    service = ConversationService(store)
    question = await service.add_user_message(
        ALICE, conversation_id, content="Does porosity matter?", mode="corpus_only"
    )
    run_id = await service.start_run(ALICE, conversation_id, workflow="qa")
    answer = await service.save_answer(
        ALICE,
        conversation_id,
        run_id,
        AnswerDraft(content="Yes [1].", mode="corpus_only"),
        RunSummary(latency_ms=1200, llm_calls=3, tokens=900),
    )
    url = f"/api/v1/conversations/{conversation_id}/messages"

    listed = api.get(url, headers=bearer(signing_key, ALICE)).json()
    page = api.get(f"{url}?limit=1&offset=1", headers=bearer(signing_key, ALICE)).json()

    assert [m["id"] for m in listed] == [str(question.id), str(answer.id)]
    assert [m["role"] for m in listed] == ["user", "assistant"]
    assert listed[1]["run_id"] == str(run_id)
    assert [m["id"] for m in page] == [str(answer.id)]
    run = store.runs[run_id]
    assert (run.status, run.latency_ms, run.llm_calls, run.tokens) == ("completed", 1200, 3, 900)


async def test_claims_come_in_answer_order_with_evidence_and_citation_snapshot(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE)
    conversation_id = UUID(start(api, signing_key, ALICE, workspace.id)["id"])
    message = await store.add_message(ALICE, answer_with_claim(conversation_id))
    assert message is not None

    response = api.get(f"/api/v1/messages/{message.id}/claims", headers=bearer(signing_key, ALICE))

    assert response.status_code == 200
    first, second = response.json()
    assert [first["position"], second["position"]] == [0, 1]
    assert first["status"] == "supported"
    assert first["support_score"] == 0.93
    assert first["evidence"][0]["score"] == 0.93
    [citation] = first["citations"]
    assert citation["source_type"] == "workspace"
    assert citation["document_title"] == "Scaffold porosity"
    assert (citation["page_start"], citation["page_end"]) == (3, 4)
    assert citation["section"] == "Results"
    assert citation["quote"] == "higher porosity increased infiltration"
    assert second["evidence"] == [] and second["citations"] == []


async def test_other_users_conversations_and_messages_are_404(
    api: TestClient, signing_key: SigningKey, store: InMemoryConversationStore
) -> None:
    workspace = store.add_workspace(ALICE)
    conversation_id = UUID(start(api, signing_key, ALICE, workspace.id)["id"])
    message = await store.add_message(ALICE, answer_with_claim(conversation_id))
    assert message is not None
    bob = bearer(signing_key, BOB)

    for response in (
        api.get(f"/api/v1/workspaces/{workspace.id}/conversations", headers=bob),
        api.post(f"/api/v1/workspaces/{workspace.id}/conversations", json={}, headers=bob),
        api.get(f"/api/v1/conversations/{conversation_id}/messages", headers=bob),
        api.get(f"/api/v1/messages/{message.id}/claims", headers=bob),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert len(store.conversations) == 1


def test_missing_resources_are_404(api: TestClient, signing_key: SigningKey) -> None:
    alice = bearer(signing_key, ALICE)

    for response in (
        api.get(f"/api/v1/workspaces/{uuid4()}/conversations", headers=alice),
        api.post(f"/api/v1/workspaces/{uuid4()}/conversations", json={}, headers=alice),
        api.get(f"/api/v1/conversations/{uuid4()}/messages", headers=alice),
        api.get(f"/api/v1/messages/{uuid4()}/claims", headers=alice),
    ):
        assert response.status_code == 404


def test_schema_literals_match_the_model_constraints() -> None:
    assert set(get_args(MessageMode)) == set(MESSAGE_MODES)
    assert set(get_args(MessageRole)) == set(MESSAGE_ROLES)
    assert set(get_args(ClaimStatus)) == set(CLAIM_STATUSES)
    assert set(get_args(CitationSourceType)) == set(CITATION_SOURCE_TYPES)
    assert set(get_args(RunStatus)) == set(RUN_STATUSES)
