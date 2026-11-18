"""LangGraph Postgres checkpointer: the saved state of QA runs (SRS §5.4, §14.2).

Checkpoints live in the `langgraph` schema (migration 0005). The library creates and migrates
its tables; `setup_checkpoint_tables` does that and is run explicitly from
`scripts/setup_checkpointer.py`, never at application startup. The QA graph keeps only plain
JSON data in its state, so checkpoints are read back with the serializer's strict allowlist:
no stored payload can name a Python class to construct.
"""

from typing import cast

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.models.migration_scope import CHECKPOINT_SCHEMA

CheckpointPool = AsyncConnectionPool[AsyncConnection[DictRow]]


def checkpoint_conninfo(database_url: str) -> str:
    """The libpq connection string for a SQLAlchemy `postgresql+psycopg://` URL."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def strict_serializer() -> JsonPlusSerializer:
    """A serializer that restores only built-in safe types."""
    return JsonPlusSerializer(allowed_msgpack_modules=None)


async def _use_checkpoint_schema(conn: AsyncConnection[DictRow]) -> None:
    """Point a new pooled connection at the checkpoint schema.

    A session-level `SET` rather than a startup option, so it also works behind the Supabase
    session pooler.
    """
    await conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(CHECKPOINT_SCHEMA)))


def create_checkpoint_pool(settings: Settings) -> CheckpointPool | None:
    """An unopened pool for the checkpointer, or None when `DATABASE_URL` is not configured."""
    if settings.database_url is None:
        return None
    return AsyncConnectionPool(
        checkpoint_conninfo(settings.database_url.get_secret_value()),
        connection_class=AsyncConnection[DictRow],
        min_size=1,
        max_size=settings.checkpoint_pool_size,
        open=False,
        configure=_use_checkpoint_schema,
        kwargs={
            "autocommit": True,
            # Server-side prepared statements break behind PgBouncer-style poolers.
            "prepare_threshold": None,
            "row_factory": dict_row,
            "connect_timeout": settings.db_connect_timeout_seconds,
        },
    )


def create_checkpointer(pool: CheckpointPool) -> AsyncPostgresSaver:
    """The checkpointer over `pool`. Call inside the running event loop."""
    return AsyncPostgresSaver(pool, serde=strict_serializer())


async def setup_checkpoint_tables(database_url: str) -> list[str]:
    """Create or migrate the checkpoint tables and enable RLS on each; returns their names.

    Raises `RuntimeError` when the schema is missing (run `alembic upgrade head` first).
    """
    async with await AsyncConnection.connect(
        checkpoint_conninfo(database_url),
        autocommit=True,
        prepare_threshold=None,
        row_factory=dict_row,
    ) as conn:
        found = await conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s", (CHECKPOINT_SCHEMA,)
        )
        if await found.fetchone() is None:
            raise RuntimeError(
                f"Schema {CHECKPOINT_SCHEMA!r} is missing; run `uv run alembic upgrade head`."
            )
        await _use_checkpoint_schema(conn)
        await AsyncPostgresSaver(conn).setup()
        rows = await conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
            (CHECKPOINT_SCHEMA,),
        )
        tables = [cast(str, row["tablename"]) for row in await rows.fetchall()]
        for table in tables:
            await conn.execute(
                sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                    sql.Identifier(CHECKPOINT_SCHEMA, table)
                )
            )
        return tables
