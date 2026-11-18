"""messages.created_at defaults to clock_timestamp()

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 12:00:00.000000

now() is the transaction start time, so messages saved in one transaction tied on created_at and
the history order fell back to the random id. clock_timestamp() keeps insert order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Default messages.created_at to the insert time, not the transaction start."""
    op.alter_column("messages", "created_at", server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    """Restore the now() default."""
    op.alter_column("messages", "created_at", server_default=sa.text("now()"))
