"""Research repository SQL against a migrated database: ownership, workspace isolation,
replace-on-rerun, cascades, and check constraints.

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back.
"""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.research import Contradiction, ResearchGap, SavedFinding
from app.models.workspace import Workspace
from app.repositories.database import create_engine_from_settings
from app.repositories.documents import DocumentRepository
from app.repositories.research import ResearchRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
REFS = [{"chunk_id": str(uuid4()), "page_start": 3, "page_end": 3, "quote": "Porosity 90%."}]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    engine = create_engine_from_settings(Settings())
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as db:
                    yield db
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> ResearchRepository:
    return ResearchRepository(session)


async def new_workspace(session: AsyncSession, user: UUID) -> Workspace:
    return await WorkspaceRepository(session).create(
        user, name="W", description=None, default_mode="corpus_only"
    )


def contradiction(text: str = "A") -> Contradiction:
    return Contradiction(
        claim_a=text,
        claim_b="B",
        evidence_refs=REFS,
        context_note="Different cell types.",
        label="potential_contradiction",
    )


async def test_findings_are_listed_only_for_their_owner_and_workspace(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    alice_ws = await new_workspace(session, ALICE)
    other_ws = await new_workspace(session, ALICE)
    finding = await repo.add_finding(
        ALICE, alice_ws.id, type="comparison", title="T", content={"rows": []}
    )

    assert [f.id for f in await repo.list_findings(ALICE, alice_ws.id)] == [finding.id]
    assert finding.content_json == {"rows": []}
    assert await repo.list_findings(BOB, alice_ws.id) == []
    assert await repo.list_findings(ALICE, other_ws.id) == []


async def test_contradictions_are_replaced_on_rerun_and_isolated(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    alice_ws = await new_workspace(session, ALICE)
    other_ws = await new_workspace(session, ALICE)
    await repo.replace_contradictions(ALICE, alice_ws.id, [contradiction("old")])
    await repo.replace_contradictions(ALICE, other_ws.id, [contradiction("other")])

    await repo.replace_contradictions(ALICE, alice_ws.id, [contradiction("new")])

    assert [c.claim_a for c in await repo.list_contradictions(ALICE, alice_ws.id)] == ["new"]
    assert [c.claim_a for c in await repo.list_contradictions(ALICE, other_ws.id)] == ["other"]
    assert await repo.list_contradictions(BOB, alice_ws.id) == []


async def test_another_user_cannot_replace_someone_elses_contradictions(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    alice_ws = await new_workspace(session, ALICE)
    await repo.replace_contradictions(ALICE, alice_ws.id, [contradiction("kept")])

    await repo.replace_contradictions(BOB, alice_ws.id, [])

    assert [c.claim_a for c in await repo.list_contradictions(ALICE, alice_ws.id)] == ["kept"]


async def test_gaps_are_replaced_per_scope(session: AsyncSession, repo: ResearchRepository) -> None:
    workspace = await new_workspace(session, ALICE)
    await repo.replace_gaps(
        ALICE, workspace.id, "field", [ResearchGap(description="field", evidence_refs=REFS)]
    )
    await repo.replace_gaps(
        ALICE, workspace.id, "corpus", [ResearchGap(description="old", evidence_refs=REFS)]
    )

    await repo.replace_gaps(
        ALICE, workspace.id, "corpus", [ResearchGap(description="new", evidence_refs=REFS)]
    )

    gaps = await repo.list_gaps(ALICE, workspace.id)
    assert sorted((g.scope, g.description) for g in gaps) == [
        ("corpus", "new"),
        ("field", "field"),
    ]
    assert gaps[0].evidence_refs == REFS
    assert await repo.list_gaps(BOB, workspace.id) == []


async def test_deleting_the_workspace_removes_its_research_records(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    workspace = await new_workspace(session, ALICE)
    await repo.add_finding(ALICE, workspace.id, type="gap", title="T", content={})
    await repo.replace_contradictions(ALICE, workspace.id, [contradiction()])
    await repo.replace_gaps(
        ALICE, workspace.id, "corpus", [ResearchGap(description="g", evidence_refs=REFS)]
    )

    await session.execute(delete(Workspace).where(Workspace.id == workspace.id))

    for model in (SavedFinding, Contradiction, ResearchGap):
        count = await session.scalar(
            select(func.count()).select_from(model).where(model.workspace_id == workspace.id)
        )
        assert count == 0, model.__tablename__


async def test_unknown_finding_type_is_rejected(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    workspace = await new_workspace(session, ALICE)

    with pytest.raises(IntegrityError, match="ck_saved_findings_type_valid"):
        await repo.add_finding(ALICE, workspace.id, type="note", title="T", content={})


async def test_workspace_name_and_documents_are_owner_only(
    session: AsyncSession, repo: ResearchRepository
) -> None:
    workspace = await new_workspace(session, ALICE)
    documents = DocumentRepository(session)
    alices = await documents.create(ALICE, uuid4(), content_hash="a", storage_path="a")
    bobs = await documents.create(BOB, uuid4(), content_hash="b", storage_path="b")
    assert alices is not None and bobs is not None

    assert await repo.workspace_name(ALICE, workspace.id) == "W"
    assert await repo.workspace_name(BOB, workspace.id) is None
    found = await repo.documents(ALICE, [alices.id, bobs.id, uuid4()])
    assert [d.id for d in found] == [alices.id]
    assert await repo.documents(ALICE, []) == []
