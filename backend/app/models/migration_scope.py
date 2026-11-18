"""Which database objects Alembic owns (D-012).

Supabase manages its own schemas (`auth`, `storage`, `realtime`, ...), and the LangGraph
Postgres checkpointer creates and migrates its own tables. Autogenerate must never try to
change or drop either, so it only sees our tables in `public`.
"""

from alembic.runtime.environment import NameFilterParentNames, NameFilterType

MIGRATED_SCHEMA = "public"

# The checkpointer's own schema: migration 0005 creates it, `scripts/setup_checkpointer.py`
# creates the tables in it. Autogenerate never reflects it.
CHECKPOINT_SCHEMA = "langgraph"

# Tables created by LangGraph's `PostgresSaver.setup()`; re-check when upgrading langgraph.
# They live in CHECKPOINT_SCHEMA; the names stay excluded in case one lands in `public`.
CHECKPOINT_TABLES: frozenset[str] = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)


def include_name(
    name: str | None, type_: NameFilterType, parent_names: NameFilterParentNames
) -> bool:
    """Alembic `include_name` hook: reflect only our own objects.

    Runs before reflection, so excluded schemas and tables are never loaded or compared.
    """
    if type_ == "schema":
        return name is None or name == MIGRATED_SCHEMA
    if type_ == "table":
        schema = parent_names.get("schema_name")
        if schema is not None and schema != MIGRATED_SCHEMA:
            return False
        return name not in CHECKPOINT_TABLES
    return True
