"""langgraph schema for the QA graph's checkpoints

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05 12:00:00.000000

The LangGraph Postgres checkpointer creates and migrates its own tables
(`scripts/setup_checkpointer.py`, never at startup). They live in their own schema so that
autogenerate, which reflects only `public`, never sees them. No role but the owner gets `USAGE`
on the schema, so the client roles cannot reach anything in it whatever its tables grant.
Downgrading drops the schema with every checkpoint in it: runs waiting for approval can no
longer be resumed.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "langgraph"


def upgrade() -> None:
    """Create the schema; only its owner may use it."""
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC, anon, authenticated")


def downgrade() -> None:
    """Drop the schema and every checkpoint in it."""
    op.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
