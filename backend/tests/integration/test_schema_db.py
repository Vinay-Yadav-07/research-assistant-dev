"""Schema safety checks against a migrated database (Supabase dev, or the CI pgvector container).

Run after `uv run alembic upgrade head`: `uv run pytest -m integration`. Needs no secrets beyond
`DATABASE_URL`, so CI runs it against a throwaway container (D-052).
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.repositories.database import create_engine_from_settings

pytestmark = pytest.mark.integration

CLIENT_ROLES = ("anon", "authenticated")
TABLE_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER"
DOMAIN_TABLES = {
    "workspaces",
    "documents",
    "workspace_documents",
    "chunks",
    "topic_profiles",
    "conversations",
    "messages",
    "claims",
    "evidence",
    "citations",
    "approvals",
    "agent_runs",
    "eval_runs",
    "eval_results",
    "saved_findings",
    "contradictions",
    "research_gaps",
    "kg_jobs",
    "kg_document_extractions",
    "kg_entity_mentions",
    "kg_relation_mentions",
    "kg_graphs",
    "kg_nodes",
    "kg_edges",
    "kg_node_mentions",
    "kg_edge_mentions",
}

PUBLIC_TABLES = text(
    """
    SELECT c.relname, c.relrowsecurity
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    """
)
CLIENT_GRANTS = text(
    """
    SELECT c.relname, r.rolname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN pg_roles r
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND r.rolname = ANY(:roles)
      AND has_table_privilege(r.oid, c.oid, :privileges)
    """
)


@pytest.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    """A connection whose transaction is always rolled back."""
    settings = Settings()
    engine = create_engine_from_settings(settings)
    if engine is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                yield conn
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def client_grants(conn: AsyncConnection) -> list[tuple[str, str]]:
    result = await conn.execute(
        CLIENT_GRANTS, {"roles": list(CLIENT_ROLES), "privileges": TABLE_PRIVILEGES}
    )
    return [(row.relname, row.rolname) for row in result]


async def test_client_roles_exist(connection: AsyncConnection) -> None:
    result = await connection.execute(
        text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
        {"roles": list(CLIENT_ROLES)},
    )

    assert sorted(result.scalars()) == sorted(CLIENT_ROLES)


async def test_every_public_table_has_row_level_security(connection: AsyncConnection) -> None:
    tables = dict((await connection.execute(PUBLIC_TABLES)).tuples().all())

    assert tables.keys() >= DOMAIN_TABLES
    assert [name for name, rls in tables.items() if not rls] == []


async def test_client_roles_have_no_privileges_on_public_tables(
    connection: AsyncConnection,
) -> None:
    assert await client_grants(connection) == []


async def test_new_tables_get_no_client_privileges(connection: AsyncConnection) -> None:
    # Created by the migration role (postgres), after the migration ran; rolled back afterwards.
    await connection.execute(text("CREATE TABLE public.zz_privilege_probe (id integer)"))

    assert await client_grants(connection) == []


async def test_pgvector_is_installed(connection: AsyncConnection) -> None:
    version = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )

    assert version is not None
