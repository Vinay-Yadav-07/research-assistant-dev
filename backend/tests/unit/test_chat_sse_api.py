"""Asking a question and resuming a run over HTTP (SRS §16.1, §16.2).

Real token verification, the real QA runner over fake providers (`qa_harness`), and the raw
`text/event-stream` body parsed back into typed events. Every path through the graph itself is
covered by `tests/unit/graphs/test_qa_graph.py`.
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.agents.query_analyzer import QueryPlan
from app.agents.synthesis import DraftAnswer
from app.api.deps import get_conversation_service, get_qa_runner
from app.api.routes.conversations import send_message
from app.core.config import Settings
from app.graphs.qa_runner import (
    ApprovalRequiredEvent,
    CitationsEvent,
    ClaimsEvent,
    DoneEvent,
    QAEvent,
    StatusEvent,
)
from app.main import create_app
from app.services.conversations import ConversationService
from tests.unit.graphs.qa_harness import (
    OTHER_USER,
    POROSITY,
    QUESTION,
    UNANSWERABLE,
    Harness,
    cited,
    harness,
    simple_plan,
)
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.services.test_retrieval import USER

EVENTS: TypeAdapter[QAEvent] = TypeAdapter(QAEvent)


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


def build_app(settings: Settings, key: SigningKey) -> FastAPI:
    app = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[key]).verifier()
    return app


def serve(app: FastAPI, h: Harness) -> FastAPI:
    """Route the runner and the history endpoints to the harness."""
    app.dependency_overrides[get_qa_runner] = lambda: h.runner
    app.dependency_overrides[get_conversation_service] = lambda: ConversationService(h.store)
    return app


@pytest.fixture
def h() -> Harness:
    return asyncio.run(harness())


@pytest.fixture
def api(settings: Settings, signing_key: SigningKey, h: Harness) -> Iterator[TestClient]:
    with TestClient(serve(build_app(settings, signing_key), h)) as client:
        yield client


def bearer(key: SigningKey, user: UUID = USER) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue(key, user)}"}


def parse_stream(body: str) -> list[QAEvent]:
    """Each SSE frame's `data:` line as a typed event; keepalive comments are skipped."""
    events = []
    for frame in body.split("\n\n"):
        data = [line.removeprefix("data: ") for line in frame.split("\n") if line[:5] == "data:"]
        if data:
            events.append(EVENTS.validate_python(json.loads("\n".join(data))))
    return events


def ask(api: TestClient, key: SigningKey, h: Harness, content: str, **kw: Any) -> Any:
    return api.post(
        f"/api/v1/conversations/{h.conversation_id}/messages",
        json={"content": content},
        headers=bearer(key, kw.get("user", USER)),
    )


def resume(api: TestClient, key: SigningKey, run_id: UUID, decision: str, **kw: Any) -> Any:
    return api.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"decision": decision},
        headers=bearer(key, kw.get("user", USER)),
    )


def pause(api: TestClient, key: SigningKey, h: Harness) -> ApprovalRequiredEvent:
    """Ask a question the empty corpus cannot answer, so the run pauses for approval."""
    h.fast.script(QueryPlan, simple_plan())
    response = ask(api, key, h, UNANSWERABLE)
    assert response.status_code == 200, response.text
    paused = parse_stream(response.text)[-1]
    assert isinstance(paused, ApprovalRequiredEvent)
    return paused


def test_answered_question_streams_progress_then_the_verified_answer(
    api: TestClient, signing_key: SigningKey, h: Harness
) -> None:
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1")]))

    response = ask(api, signing_key, h, QUESTION)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_stream(response.text)
    assert isinstance(events[0], StatusEvent) and events[0].stage == "analyzing"
    assert [type(e) for e in events[-3:]] == [ClaimsEvent, CitationsEvent, DoneEvent]
    done = events[-1]
    assert isinstance(done, DoneEvent) and done.outcome == "answered"
    assert done.message.content == POROSITY
    assert done.message.id in h.store.messages


def test_paused_run_streams_the_approval_request_and_resumes(
    settings: Settings, signing_key: SigningKey
) -> None:
    h = asyncio.run(harness(corpus=()))
    app = build_app(settings, signing_key)
    app.dependency_overrides[get_qa_runner] = lambda: h.runner
    with TestClient(app) as api:
        paused = pause(api, signing_key, h)
        assert set(paused.request.options) == {"corpus_only", "corpus_web", "general_knowledge"}

        response = resume(api, signing_key, paused.run_id, "corpus_only")

    assert response.status_code == 200
    done = parse_stream(response.text)[-1]
    assert isinstance(done, DoneEvent)
    assert (done.run_id, done.outcome) == (paused.run_id, "abstained")
    assert h.store.approvals[0].decision == "corpus_only"


def test_resume_rejects_other_users_bad_decisions_and_finished_runs(
    settings: Settings, signing_key: SigningKey
) -> None:
    h = asyncio.run(harness(corpus=()))
    app = build_app(settings, signing_key)
    app.dependency_overrides[get_qa_runner] = lambda: h.runner
    with TestClient(app) as api:
        run_id = pause(api, signing_key, h).run_id

        other = resume(api, signing_key, run_id, "corpus_only", user=OTHER_USER)
        missing = resume(api, signing_key, uuid4(), "corpus_only")
        invalid = resume(api, signing_key, run_id, "web_only")
        assert resume(api, signing_key, run_id, "corpus_only").status_code == 200
        finished = resume(api, signing_key, run_id, "general_knowledge")

    assert (other.status_code, other.json()["error"]["code"]) == (404, "not_found")
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert finished.status_code == 409
    assert finished.headers["content-type"] == "application/json"


def test_rejected_questions_get_a_json_error_before_any_stream(
    api: TestClient, signing_key: SigningKey, h: Harness
) -> None:
    empty = ask(api, signing_key, h, "   ")
    other = ask(api, signing_key, h, QUESTION, user=OTHER_USER)
    anonymous = api.post(
        f"/api/v1/conversations/{h.conversation_id}/messages", json={"content": QUESTION}
    )

    assert (empty.status_code, empty.headers["content-type"]) == (422, "application/json")
    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert h.store.runs == {} and h.store.messages == {}


def test_without_a_database_both_endpoints_answer_503(
    settings: Settings, signing_key: SigningKey
) -> None:
    with TestClient(build_app(settings, signing_key)) as api:
        asked = api.post(
            f"/api/v1/conversations/{uuid4()}/messages",
            json={"content": QUESTION},
            headers=bearer(signing_key),
        )
        resumed = api.post(
            f"/api/v1/runs/{uuid4()}/resume",
            json={"decision": "corpus_only"},
            headers=bearer(signing_key),
        )

        run = api.get(f"/api/v1/runs/{uuid4()}", headers=bearer(signing_key))

    assert asked.status_code == resumed.status_code == run.status_code == 503


def history(api: TestClient, key: SigningKey, h: Harness, **kw: Any) -> Any:
    return api.get(
        f"/api/v1/conversations/{h.conversation_id}/messages",
        headers=bearer(key, kw.get("user", USER)),
    )


def get_run(api: TestClient, key: SigningKey, run_id: UUID, **kw: Any) -> Any:
    return api.get(f"/api/v1/runs/{run_id}", headers=bearer(key, kw.get("user", USER)))


def test_history_includes_each_answers_claims_and_citations(
    api: TestClient, signing_key: SigningKey, h: Harness
) -> None:
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1")]))
    events = parse_stream(ask(api, signing_key, h, QUESTION).text)
    claims = next(e for e in events if isinstance(e, ClaimsEvent))
    done = events[-1]
    assert isinstance(done, DoneEvent)

    response = history(api, signing_key, h)

    assert response.status_code == 200
    question, answer = response.json()
    assert (question["role"], question["run_id"], question["claims"]) == (
        "user",
        str(done.run_id),
        [],
    )
    assert answer["id"] == str(done.message.id)
    assert answer["claims"] == [c.model_dump(mode="json") for c in claims.claims]
    assert answer["claims"][0]["citations"][0]["page_start"] is not None


def test_a_reloaded_conversation_finds_its_paused_run_and_resumes_it(
    settings: Settings, signing_key: SigningKey
) -> None:
    h = asyncio.run(harness(corpus=()))
    with TestClient(serve(build_app(settings, signing_key), h)) as api:
        paused = pause(api, signing_key, h)

        # A reload: the history ends with an unanswered question whose run is paused.
        [question] = history(api, signing_key, h).json()
        run = get_run(api, signing_key, UUID(question["run_id"]))
        other = get_run(api, signing_key, paused.run_id, user=OTHER_USER)
        missing = get_run(api, signing_key, uuid4())
        resumed = resume(api, signing_key, paused.run_id, "corpus_only")
        finished = get_run(api, signing_key, paused.run_id)

    assert UUID(question["run_id"]) == paused.run_id
    assert run.status_code == 200
    assert run.json()["status"] == "interrupted"
    assert run.json()["approval"] == paused.request.model_dump(mode="json")
    assert run.json()["approval"]["sub_questions"]
    assert (other.status_code, other.json()["error"]["code"]) == (404, "not_found")
    assert missing.status_code == 404
    assert resumed.status_code == 200
    assert (finished.json()["status"], finished.json()["approval"]) == ("completed", None)
    assert finished.json()["finished_at"] is not None


def test_a_paused_run_without_its_checkpoint_returns_the_logged_request(
    settings: Settings, signing_key: SigningKey
) -> None:
    h = asyncio.run(harness(corpus=()))
    with TestClient(serve(build_app(settings, signing_key), h)) as api:
        paused = pause(api, signing_key, h)
        asyncio.run(h.checkpointer.adelete_thread(str(paused.run_id)))

        run = get_run(api, signing_key, paused.run_id)

    approval = run.json()["approval"]
    assert (approval["reason"], approval["sub_questions"]) == (paused.request.reason, [])
    assert approval["options"] == paused.request.options


async def test_the_answer_is_saved_when_the_client_stops_listening() -> None:
    h = await harness()
    h.fast.script(QueryPlan, simple_plan())
    h.strong.script(DraftAnswer, DraftAnswer(sentences=[cited(POROSITY, "E1")]))
    run = await h.runner.start(USER, h.conversation_id, QUESTION)

    stream = send_message(run)
    first = await anext(stream)
    await stream.aclose()  # what the server does when the client disconnects

    assert isinstance(first, StatusEvent)
    for _ in range(200):
        if h.store.runs[run.run_id].status == "completed":
            break
        await asyncio.sleep(0.01)
    assert h.store.runs[run.run_id].status == "completed"
    assert any(m.role == "assistant" for m in h.store.messages.values())
