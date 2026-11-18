"""Chunk search SQL against a migrated database: workspace and user isolation (FR-08), exact
dense search that never uses the HNSW index (D-059), and safe OR full-text queries.

Runs in CI's pgvector container (no secrets) and against Supabase dev. Every test runs in a
transaction that is rolled back.
"""

import hashlib
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models._types import EMBEDDING_DIMENSION
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.workspace import Workspace, WorkspaceDocument
from app.repositories.chunks import ChunkRepository
from app.repositories.database import create_engine_from_settings

pytestmark = pytest.mark.integration

ALICE = uuid4()
BOB = uuid4()
MODEL = "test-model"


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
def repo(session: AsyncSession) -> ChunkRepository:
    return ChunkRepository(session)


def vector(*weights: tuple[int, float]) -> list[float]:
    """A vector that is zero except at the given (index, value) positions."""
    values = [0.0] * EMBEDDING_DIMENSION
    for index, value in weights:
        values[index] = value
    return values


QUERY = vector((0, 1.0))


async def workspace(session: AsyncSession, user: UUID) -> UUID:
    row = Workspace(user_id=user, name="W")
    session.add(row)
    await session.flush()
    return row.id


async def document(
    session: AsyncSession,
    user: UUID,
    workspace_ids: list[UUID],
    chunks: list[tuple[str, list[float]]],
    *,
    status: str = "ready",
    model: str = MODEL,
    title: str | None = "Paper",
    doi: str | None = None,
) -> list[UUID]:
    """A document linked to `workspace_ids` with `chunks` (text, embedding); returns chunk ids."""
    row = Document(
        user_id=user,
        title=title,
        doi=doi,
        content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        status=status,
    )
    session.add(row)
    await session.flush()
    for workspace_id in workspace_ids:
        session.add(WorkspaceDocument(workspace_id=workspace_id, document_id=row.id))
    rows = [
        Chunk(
            document_id=row.id,
            chunk_index=index,
            page_start=index + 1,
            page_end=index + 1,
            section="Results",
            text=body,
            token_count=len(body.split()),
            content_hash=str(index),
            embedding=embedding,
            embedding_model=model,
        )
        for index, (body, embedding) in enumerate(chunks)
    ]
    session.add_all(rows)
    await session.flush()
    return [chunk.id for chunk in rows]


async def dense(
    repo: ChunkRepository, user: UUID, workspace_id: UUID, limit: int = 30
) -> list[UUID]:
    hits = await repo.dense_search(user, workspace_id, QUERY, embedding_model=MODEL, limit=limit)
    return [hit.chunk_id for hit in hits]


async def lexical(repo: ChunkRepository, user: UUID, workspace_id: UUID, query: str) -> list[UUID]:
    return [hit.chunk_id for hit in await repo.lexical_search(user, workspace_id, query, limit=30)]


# --- isolation (FR-08) ---


async def test_other_workspace_is_never_returned_even_when_closer(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    mine, other = await workspace(session, ALICE), await workspace(session, ALICE)
    [far] = await document(session, ALICE, [mine], [("scaffold porosity", vector((1, 1.0)))])
    await document(session, ALICE, [other], [("scaffold porosity exact match", QUERY)])

    assert await dense(repo, ALICE, mine) == [far]
    assert await lexical(repo, ALICE, mine, "scaffold porosity exact match") == [far]


async def test_other_users_workspace_returns_nothing(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    alice_ws = await workspace(session, ALICE)
    [chunk] = await document(session, ALICE, [alice_ws], [("hydrogel stiffness", QUERY)])

    assert await dense(repo, BOB, alice_ws) == []
    assert await lexical(repo, BOB, alice_ws, "hydrogel stiffness") == []
    assert await repo.load(BOB, alice_ws, [chunk]) == []
    assert await repo.workspace_owned(BOB, alice_ws) is False
    assert await dense(repo, ALICE, alice_ws) == [chunk]


async def test_load_only_returns_the_workspaces_chunks(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    mine, other = await workspace(session, ALICE), await workspace(session, ALICE)
    [own] = await document(session, ALICE, [mine], [("own", QUERY)])
    [foreign] = await document(session, ALICE, [other], [("foreign", QUERY)])

    records = await repo.load(ALICE, mine, [own, foreign])

    assert [record.chunk_id for record in records] == [own]
    [record] = records
    assert (record.page_start, record.section, record.text) == (1, "Results", "own")


async def test_shared_document_is_found_from_both_workspaces(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    first, second = await workspace(session, ALICE), await workspace(session, ALICE)
    [chunk] = await document(session, ALICE, [first, second], [("shared", QUERY)])

    assert await dense(repo, ALICE, first) == [chunk]
    assert await dense(repo, ALICE, second) == [chunk]


async def test_unready_documents_and_other_models_are_excluded(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    ws = await workspace(session, ALICE)
    [ready] = await document(session, ALICE, [ws], [("porosity ready", QUERY)])
    await document(session, ALICE, [ws], [("porosity parsing", QUERY)], status="embedding")
    [other_model] = await document(session, ALICE, [ws], [("porosity old", QUERY)], model="old")

    assert await dense(repo, ALICE, ws) == [ready]
    # Full text does not depend on the embedding model.
    assert set(await lexical(repo, ALICE, ws, "porosity")) == {ready, other_model}


# --- exact dense search (D-059) ---


async def test_dense_search_orders_by_cosine_distance(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    ws = await workspace(session, ALICE)
    ids = await document(
        session,
        ALICE,
        [ws],
        [
            ("far", vector((1, 1.0))),
            ("near", vector((0, 1.0), (1, 0.2))),
            ("same", QUERY),
            ("opposite", vector((0, -1.0))),
        ],
    )
    far, near, same, opposite = ids

    hits = await repo.dense_search(ALICE, ws, QUERY, embedding_model=MODEL, limit=3)

    assert [hit.chunk_id for hit in hits] == [same, near, far]
    assert hits[0].score == pytest.approx(0.0, abs=1e-6)


async def test_small_workspace_gets_full_top_k_among_many_closer_chunks(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    """Regression for the HNSW post-filtering known issue (task #7)."""
    big = await workspace(session, BOB)
    await document(
        session, BOB, [big], [(f"close {i}", vector((0, 1.0), (2, i / 1000))) for i in range(400)]
    )
    small = await workspace(session, ALICE)
    own = await document(
        session, ALICE, [small], [(f"far {i}", vector((3, 1.0), (4, i / 10))) for i in range(12)]
    )
    await session.execute(text("ANALYZE chunks"))

    assert set(await dense(repo, ALICE, small, limit=10)) <= set(own)
    assert len(await dense(repo, ALICE, small, limit=10)) == 10
    assert len(await dense(repo, ALICE, small, limit=30)) == 12


async def explain(session: AsyncSession, statement: str, parameters: Any) -> str:
    connection = await session.connection()
    result = await connection.exec_driver_sql(f"EXPLAIN {statement}", parameters)
    return "\n".join(row[0] for row in result)


async def test_dense_query_never_uses_the_hnsw_index(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    ws = await workspace(session, ALICE)
    await document(session, ALICE, [ws], [(f"c{i}", vector((i % 50, 1.0))) for i in range(200)])
    await session.execute(text("ANALYZE chunks"))
    # Make an index scan as attractive as possible to the planner.
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    captured: list[tuple[str, Any]] = []
    connection = await session.connection()

    def capture(conn: Any, cursor: Any, statement: str, parameters: Any, *args: Any) -> None:
        if "<=>" in statement:
            captured.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        await dense(repo, ALICE, ws)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)

    [(statement, parameters)] = captured
    plan = await explain(session, statement, parameters)
    assert "MATERIALIZED" in statement
    assert "ix_chunks_embedding" not in plan, plan

    # Control: the same planner settings do pick HNSW for an unscoped nearest-neighbour query,
    # so the assertion above would catch a regression.
    naive = await explain(
        session,
        "SELECT id FROM chunks ORDER BY embedding <=> %(q)s::vector LIMIT 30",
        {"q": str(QUERY)},
    )
    assert "ix_chunks_embedding" in naive, naive


# --- full text (OR of plainto_tsquery lexemes) ---


async def test_lexical_matches_any_term_and_ranks_by_coverage(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    ws = await workspace(session, ALICE)
    one_term, all_terms, none = await document(
        session,
        ALICE,
        [ws],
        [
            ("Porosity was measured by micro-CT.", QUERY),
            ("Scaffold porosity improved fibroblast infiltration.", QUERY),
            ("Unrelated text about cardiac patches.", QUERY),
        ],
    )

    found = await lexical(
        repo, ALICE, ws, "How does scaffold porosity affect fibroblast infiltration?"
    )

    assert found == [all_terms, one_term]
    assert none not in found


async def test_section_heading_is_searchable(repo: ChunkRepository, session: AsyncSession) -> None:
    ws = await workspace(session, ALICE)
    [chunk] = await document(session, ALICE, [ws], [("body without the word", QUERY)])

    assert await lexical(repo, ALICE, ws, "results") == [chunk]


@pytest.mark.parametrize(
    "query",
    [
        "porosity & stiffness",
        "porosity | stiffness",
        "!porosity",
        "porosity:*",
        "(porosity) & (",
        "scaffold's porosity",
        "'porosity' ' ''",
        "a & | ! : ( ) ' <-> <2> \\ \"",
        "the and of a",
        "?!",
        "",
    ],
)
async def test_lexical_never_fails_on_operator_characters_or_stopwords(
    repo: ChunkRepository, session: AsyncSession, query: str
) -> None:
    ws = await workspace(session, ALICE)
    [chunk] = await document(
        session, ALICE, [ws], [("Porosity and stiffness of scaffolds.", QUERY)]
    )

    found = await lexical(repo, ALICE, ws, query)

    assert found in ([], [chunk])
    if "porosity" in query.lower():
        assert found == [chunk]


# --- named papers (SRS §7.4) ---


async def document_of(session: AsyncSession, chunk_id: UUID) -> UUID:
    found = await session.scalar(select(Chunk.document_id).where(Chunk.id == chunk_id))
    assert found is not None
    return found


async def test_document_filter_narrows_both_searches_within_the_workspace(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    mine, other = await workspace(session, ALICE), await workspace(session, ALICE)
    [wanted] = await document(session, ALICE, [mine], [("scaffold porosity", vector((1, 1.0)))])
    await document(session, ALICE, [mine], [("scaffold porosity", QUERY)])
    [foreign] = await document(session, ALICE, [other], [("scaffold porosity", QUERY)])
    named = [await document_of(session, wanted), await document_of(session, foreign)]

    dense_hits = await repo.dense_search(
        ALICE, mine, QUERY, embedding_model=MODEL, limit=30, document_ids=named
    )
    lexical_hits = await repo.lexical_search(
        ALICE, mine, "scaffold porosity", limit=30, document_ids=named
    )

    assert [hit.chunk_id for hit in dense_hits] == [wanted]
    assert [hit.chunk_id for hit in lexical_hits] == [wanted]


async def test_paper_references_match_titles_either_way_and_dois(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    mine = await workspace(session, ALICE)
    [by_title] = await document(
        session, ALICE, [mine], [("a", QUERY)], title="Architected Hydrogels for Tissue"
    )
    [by_doi] = await document(
        session, ALICE, [mine], [("b", QUERY)], title=None, doi="10.1000/xyz123"
    )
    [short] = await document(session, ALICE, [mine], [("c", QUERY)], title="Gels")
    await document(session, ALICE, [mine], [("d", QUERY)], title="Unrelated")

    assert await repo.match_documents(ALICE, mine, ["architected HYDROGELS"]) == [
        await document_of(session, by_title)
    ]
    assert await repo.match_documents(ALICE, mine, ["the Gels paper by Smith"]) == [
        await document_of(session, short)
    ]
    assert await repo.match_documents(ALICE, mine, ["10.1000/XYZ123"]) == [
        await document_of(session, by_doi)
    ]
    assert await repo.match_documents(ALICE, mine, ["%", "__", "ab", "  "]) == []


async def test_paper_references_never_match_outside_the_owned_workspace(
    repo: ChunkRepository, session: AsyncSession
) -> None:
    mine, other = await workspace(session, ALICE), await workspace(session, ALICE)
    await document(session, ALICE, [other], [("a", QUERY)], title="Hydrogel review")
    await document(session, ALICE, [mine], [("b", QUERY)], title="Hydrogel draft", status="parsing")
    bobs = await workspace(session, BOB)
    await document(session, BOB, [bobs], [("c", QUERY)], title="Hydrogel review")

    assert await repo.match_documents(ALICE, mine, ["hydrogel"]) == []
    assert await repo.match_documents(BOB, mine, ["hydrogel"]) == []
    assert await repo.match_documents(ALICE, bobs, ["hydrogel"]) == []
