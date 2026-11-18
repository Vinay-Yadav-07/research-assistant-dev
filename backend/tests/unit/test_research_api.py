"""Research endpoints over HTTP with real token verification and an in-memory store."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.literature_analysis import (
    NOT_REPORTED,
    ContradictionChecksDraft,
    FindingsDraft,
    GapsDraft,
    PaperCells,
    SynthesisDraft,
)
from app.api.deps import get_literature_analysis_agent, get_research_service
from app.core.config import Settings
from app.main import create_app
from app.models.document import Document
from app.models.research import Contradiction, ResearchGap, SavedFinding
from app.providers.fakes.llm import FakeLLM
from app.services.research import ResearchService
from tests.unit.agents.test_literature_analysis import (
    FINDINGS,
    PAPER_A,
    PAPER_B,
    agent,
    checks,
    store_with_papers,
)
from tests.unit.jwt_helpers import SUPABASE_URL, FakeJWKS, SigningKey, ec_key, issue
from tests.unit.services.test_retrieval import USER, WORKSPACE

URL = f"/api/v1/workspaces/{WORKSPACE}/compare"
SYNTHESIZE_URL = f"/api/v1/workspaces/{WORKSPACE}/synthesize"
CONTRADICTIONS_URL = f"/api/v1/workspaces/{WORKSPACE}/contradictions"
GAPS_URL = f"/api/v1/workspaces/{WORKSPACE}/gaps"
FINDINGS_URL = f"/api/v1/workspaces/{WORKSPACE}/findings"
GAP = {"text": "Neither study tested in vivo.", "papers": ["P1", "P2"], "citations": ["E1", "E3"]}


class InMemoryResearchStore:
    def __init__(self) -> None:
        self.contradictions: dict[tuple[UUID, UUID], list[Contradiction]] = {}
        self.gaps: dict[tuple[UUID, UUID, str], list[ResearchGap]] = {}
        self.findings: list[SavedFinding] = []
        self.documents_by_id: dict[UUID, Document] = {}
        self.commits = 0

    async def workspace_name(self, user_id: UUID, workspace_id: UUID) -> str | None:
        return "Scaffolds" if (user_id, workspace_id) == (USER, WORKSPACE) else None

    async def add_finding(
        self, user_id: UUID, workspace_id: UUID, *, type: str, title: str, content: dict[str, Any]
    ) -> SavedFinding:
        finding = SavedFinding(
            id=uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            type=type,
            title=title,
            content_json=content,
            created_at=datetime(2026, 10, 10, tzinfo=UTC),
        )
        self.findings.append(finding)
        return finding

    async def list_findings(self, user_id: UUID, workspace_id: UUID) -> list[SavedFinding]:
        return [f for f in self.findings if (f.user_id, f.workspace_id) == (user_id, workspace_id)]

    async def documents(self, user_id: UUID, document_ids: Sequence[UUID]) -> list[Document]:
        found = (self.documents_by_id.get(i) for i in document_ids)
        return [d for d in found if d is not None and d.user_id == user_id]

    async def replace_contradictions(
        self, user_id: UUID, workspace_id: UUID, contradictions: Sequence[Contradiction]
    ) -> None:
        self.contradictions[(user_id, workspace_id)] = list(contradictions)

    async def replace_gaps(
        self, user_id: UUID, workspace_id: UUID, scope: str, gaps: Sequence[ResearchGap]
    ) -> None:
        self.gaps[(user_id, workspace_id, scope)] = list(gaps)

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def research_store() -> InMemoryResearchStore:
    return InMemoryResearchStore()


@pytest.fixture
def signing_key() -> SigningKey:
    return ec_key("test-key")


@pytest.fixture
async def api(
    settings: Settings, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> AsyncIterator[TestClient]:
    store = await store_with_papers()
    llm = FakeLLM(
        structured={
            PaperCells: [{"cells": []}, {"cells": []}],
            SynthesisDraft: [{"themes": []}],
            FindingsDraft: [FINDINGS],
            ContradictionChecksDraft: [checks(("C1", "potential_contradiction", "Conflict."))],
            GapsDraft: [{"gaps": [GAP]}],
        }
    )
    app: FastAPI = create_app(settings.model_copy(update={"supabase_url": SUPABASE_URL}))
    app.state.jwt_verifier = FakeJWKS(keys=[signing_key]).verifier()
    app.dependency_overrides[get_literature_analysis_agent] = lambda: agent(store, llm)
    app.dependency_overrides[get_research_service] = lambda: ResearchService(research_store)
    with TestClient(app) as client:
        yield client


def post(api: TestClient, key: SigningKey, user: UUID, body: dict[str, Any], url: str = URL) -> Any:
    return api.post(url, json=body, headers={"Authorization": f"Bearer {issue(key, user)}"})


def test_compare_returns_a_table(api: TestClient, signing_key: SigningKey) -> None:
    response = post(api, signing_key, USER, {"document_ids": [str(PAPER_A), str(PAPER_B)]})

    assert response.status_code == 200
    papers = response.json()["papers"]
    assert [p["document_id"] for p in papers] == [str(PAPER_A), str(PAPER_B)]
    assert all(c["text"] == NOT_REPORTED for p in papers for c in p["cells"])


def test_other_users_workspace_is_404(api: TestClient, signing_key: SigningKey) -> None:
    response = post(api, signing_key, uuid4(), {"document_ids": [str(PAPER_A), str(PAPER_B)]})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "ids", [[], [str(PAPER_A)], [str(PAPER_A), str(PAPER_A)], ["not-a-uuid", str(PAPER_B)]]
)
def test_invalid_selection_is_422(api: TestClient, signing_key: SigningKey, ids: list[str]) -> None:
    assert post(api, signing_key, USER, {"document_ids": ids}).status_code == 422


def test_requires_a_token(api: TestClient) -> None:
    assert api.post(URL, json={"document_ids": [str(PAPER_A), str(PAPER_B)]}).status_code == 401


def test_synthesize_returns_themes(api: TestClient, signing_key: SigningKey) -> None:
    body = {"topic": " scaffolds ", "document_ids": [str(PAPER_A), str(PAPER_B)]}
    response = post(api, signing_key, USER, body, SYNTHESIZE_URL)

    assert response.status_code == 200
    assert response.json() == {"topic": "scaffolds", "themes": []}


def test_synthesize_other_users_workspace_is_404(api: TestClient, signing_key: SigningKey) -> None:
    body = {"topic": "scaffolds", "document_ids": [str(PAPER_A), str(PAPER_B)]}
    assert post(api, signing_key, uuid4(), body, SYNTHESIZE_URL).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"topic": "", "document_ids": [str(PAPER_A), str(PAPER_B)]},
        {"topic": "x" * 501, "document_ids": [str(PAPER_A), str(PAPER_B)]},
        {"document_ids": [str(PAPER_A), str(PAPER_B)]},
        {"topic": "scaffolds", "document_ids": [str(PAPER_A)]},
    ],
)
def test_synthesize_invalid_body_is_422(
    api: TestClient, signing_key: SigningKey, body: dict[str, Any]
) -> None:
    assert post(api, signing_key, USER, body, SYNTHESIZE_URL).status_code == 422


def test_contradictions_are_returned_and_stored(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    body = {"topic": " scaffolds ", "document_ids": [str(PAPER_A), str(PAPER_B)]}
    response = post(api, signing_key, USER, body, CONTRADICTIONS_URL)

    assert response.status_code == 200
    (pair,) = response.json()["contradictions"]
    assert pair["label"] == "potential_contradiction"
    assert pair["finding_b"]["document_id"] == str(PAPER_B)
    (row,) = research_store.contradictions[(USER, WORKSPACE)]
    assert (row.claim_a, row.claim_b) == (
        pair["finding_a"]["text"],
        pair["finding_b"]["text"],
    )
    assert (row.label, row.context_note) == ("potential_contradiction", "Conflict.")
    assert {ref["side"] for ref in row.evidence_refs} == {"a", "b"}
    assert research_store.commits == 1


def test_contradictions_in_other_users_workspace_are_404_and_store_nothing(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    body = {"topic": "scaffolds", "document_ids": [str(PAPER_A), str(PAPER_B)]}
    assert post(api, signing_key, uuid4(), body, CONTRADICTIONS_URL).status_code == 404
    assert research_store.contradictions == {} and research_store.commits == 0


def test_contradictions_invalid_body_is_422(api: TestClient, signing_key: SigningKey) -> None:
    body = {"topic": "", "document_ids": [str(PAPER_A), str(PAPER_B)]}
    assert post(api, signing_key, USER, body, CONTRADICTIONS_URL).status_code == 422


def test_gaps_are_returned_and_stored_as_corpus_gaps(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    body = {"document_ids": [str(PAPER_A), str(PAPER_B)]}
    response = post(api, signing_key, USER, body, GAPS_URL)

    assert response.status_code == 200
    (gap,) = response.json()["gaps"]
    assert gap["document_ids"] == [str(PAPER_A), str(PAPER_B)]
    (row,) = research_store.gaps[(USER, WORKSPACE, "corpus")]
    assert row.description == gap["text"] and len(row.evidence_refs) == 2
    assert research_store.commits == 1


def test_gaps_in_other_users_workspace_are_404_and_store_nothing(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    body = {"document_ids": [str(PAPER_A), str(PAPER_B)]}
    assert post(api, signing_key, uuid4(), body, GAPS_URL).status_code == 404
    assert research_store.gaps == {} and research_store.commits == 0


def test_gaps_invalid_body_is_422(api: TestClient, signing_key: SigningKey) -> None:
    body = {"document_ids": [str(PAPER_A)]}
    assert post(api, signing_key, USER, body, GAPS_URL).status_code == 422


CITED_ANSWER = {
    "claims": [
        {
            "text": "PCL supports growth.",
            "citations": [
                {
                    "source_type": "corpus",
                    "document_id": str(PAPER_A),
                    "document_title": "Paper A",
                    "page_start": 2,
                    "page_end": 2,
                    "quote": "PCL",
                }
            ],
        }
    ]
}


def get(api: TestClient, key: SigningKey, user: UUID, url: str) -> Any:
    return api.get(url, headers={"Authorization": f"Bearer {issue(key, user)}"})


def save(api: TestClient, key: SigningKey, user: UUID = USER, **fields: Any) -> Any:
    body = {"type": "answer", "title": " PCL ", "content": CITED_ANSWER, **fields}
    return post(api, key, user, body, FINDINGS_URL)


def test_saved_findings_are_listed(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    response = save(api, signing_key)

    assert response.status_code == 201
    saved = response.json()
    assert (saved["type"], saved["title"], saved["content"]) == ("answer", "PCL", CITED_ANSWER)
    assert research_store.commits == 1
    assert get(api, signing_key, USER, FINDINGS_URL).json() == [saved]


@pytest.mark.parametrize(
    "fields", [{"type": "note"}, {"title": ""}, {"title": "x" * 301}, {"content": "text"}]
)
def test_invalid_finding_is_422(
    api: TestClient, signing_key: SigningKey, fields: dict[str, Any]
) -> None:
    assert save(api, signing_key, **fields).status_code == 422


@pytest.mark.parametrize("suffix", ["", "/export", "/export?format=bibtex"])
def test_findings_of_other_users_workspace_are_404(
    api: TestClient, signing_key: SigningKey, suffix: str
) -> None:
    save(api, signing_key)
    assert get(api, signing_key, uuid4(), FINDINGS_URL + suffix).status_code == 404


def test_saving_into_other_users_workspace_is_404_and_stores_nothing(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    assert save(api, signing_key, uuid4()).status_code == 404
    assert research_store.findings == [] and research_store.commits == 0


def test_markdown_export_is_a_file_with_references(
    api: TestClient, signing_key: SigningKey
) -> None:
    save(api, signing_key)
    response = get(api, signing_key, USER, f"{FINDINGS_URL}/export?format=md")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="findings.md"'
    assert "## PCL" in response.text and "- PCL supports growth. [1]" in response.text
    assert '1. Paper A, p. 2 — "PCL"' in response.text


def test_bibtex_export_lists_cited_papers_the_user_owns(
    api: TestClient, signing_key: SigningKey, research_store: InMemoryResearchStore
) -> None:
    research_store.documents_by_id[PAPER_A] = Document(
        id=PAPER_A, user_id=USER, title="Paper A", authors=["Ada Lovelace"], year=2021
    )
    save(api, signing_key)
    response = get(api, signing_key, USER, f"{FINDINGS_URL}/export?format=bibtex")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-bibtex; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="findings.bib"'
    assert response.text.startswith("@misc{lovelace2021,\n  title = {Paper A},")


def test_unknown_export_format_is_422(api: TestClient, signing_key: SigningKey) -> None:
    assert get(api, signing_key, USER, f"{FINDINGS_URL}/export?format=pdf").status_code == 422
