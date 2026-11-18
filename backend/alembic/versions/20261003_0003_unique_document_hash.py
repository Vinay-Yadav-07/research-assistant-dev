"""unique (user_id, content_hash) on documents

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 12:00:00.000000

Replaces the plain index: a concurrent second upload of the same file now fails on insert and
is answered as a duplicate (FR-03, D-057). The constraint's index serves the duplicate lookup.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the index for a unique constraint (fails if duplicates already exist)."""
    op.drop_index("ix_documents_user_id_content_hash", table_name="documents")
    op.create_unique_constraint(
        op.f("uq_documents_user_id_content_hash"), "documents", ["user_id", "content_hash"]
    )


def downgrade() -> None:
    """Restore the plain index."""
    op.drop_constraint(op.f("uq_documents_user_id_content_hash"), "documents", type_="unique")
    op.create_index(
        "ix_documents_user_id_content_hash", "documents", ["user_id", "content_hash"], unique=False
    )
