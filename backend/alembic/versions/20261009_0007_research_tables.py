"""research tables: saved findings, contradictions, research gaps

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 22:28:50.426102

Phase 4 tables for FR-20, FR-21, and FR-26. RLS is enabled explicitly on each new table, as in
0002 and 0004 (D-040); 0002's default-privilege revokes cover client roles.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("contradictions", "research_gaps", "saved_findings")


def upgrade() -> None:
    """Create the tables and enable RLS on them."""
    op.create_table(
        "contradictions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("claim_a", sa.Text(), nullable=False),
        sa.Column("claim_b", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_note", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "label IN ('potential_contradiction', 'context_dependent')",
            name=op.f("ck_contradictions_label_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_contradictions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contradictions")),
    )
    op.create_index(op.f("ix_contradictions_user_id"), "contradictions", ["user_id"], unique=False)
    op.create_index(
        "ix_contradictions_workspace_id_created_at",
        "contradictions",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "research_gaps",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope IN ('corpus', 'field')", name=op.f("ck_research_gaps_scope_valid")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_research_gaps_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_gaps")),
    )
    op.create_index(op.f("ix_research_gaps_user_id"), "research_gaps", ["user_id"], unique=False)
    op.create_index(
        "ix_research_gaps_workspace_id_created_at",
        "research_gaps",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "saved_findings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('answer', 'comparison', 'contradiction', 'gap', 'review')",
            name=op.f("ck_saved_findings_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_saved_findings_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_findings")),
    )
    op.create_index(op.f("ix_saved_findings_user_id"), "saved_findings", ["user_id"], unique=False)
    op.create_index(
        "ix_saved_findings_workspace_id_created_at",
        "saved_findings",
        ["workspace_id", "created_at"],
        unique=False,
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Drop the tables."""
    op.drop_index("ix_saved_findings_workspace_id_created_at", table_name="saved_findings")
    op.drop_index(op.f("ix_saved_findings_user_id"), table_name="saved_findings")
    op.drop_table("saved_findings")
    op.drop_index("ix_research_gaps_workspace_id_created_at", table_name="research_gaps")
    op.drop_index(op.f("ix_research_gaps_user_id"), table_name="research_gaps")
    op.drop_table("research_gaps")
    op.drop_index("ix_contradictions_workspace_id_created_at", table_name="contradictions")
    op.drop_index(op.f("ix_contradictions_user_id"), table_name="contradictions")
    op.drop_table("contradictions")
