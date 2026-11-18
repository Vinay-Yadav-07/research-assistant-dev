"""knowledge graph tables: jobs, per-paper extractions and mentions, workspace nodes and edges

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18 12:00:00.000000

FR-33, SRS §9.1, D-081. RLS is enabled explicitly on each new table, as in 0002, 0004 and 0007
(D-040); 0002's default-privilege revokes cover client roles.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "kg_jobs",
    "kg_document_extractions",
    "kg_entity_mentions",
    "kg_relation_mentions",
    "kg_graphs",
    "kg_nodes",
    "kg_edges",
    "kg_node_mentions",
    "kg_edge_mentions",
)
ENTITY_TYPES = "'concept', 'method', 'dataset', 'metric', 'task', 'tool', 'finding'"
RELATION_TYPES = "'uses', 'evaluated_on', 'measured_by', 'addresses', 'compared_with', 'reports'"


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    """Create the tables and indexes and enable RLS on them."""
    op.create_table(
        "kg_jobs",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("documents_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("documents_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("current_document_id", sa.Uuid(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("call_budget", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('generate', 'update')", name=op.f("ck_kg_jobs_kind_valid")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name=op.f("ck_kg_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "phase IS NULL OR phase IN ('extracting', 'building')",
            name=op.f("ck_kg_jobs_phase_valid"),
        ),
        _fk("kg_jobs", "workspace_id", "workspaces", "CASCADE"),
        _fk("kg_jobs", "current_document_id", "documents", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_jobs")),
    )
    op.create_index(op.f("ix_kg_jobs_user_id"), "kg_jobs", ["user_id"], unique=False)
    op.create_index(
        "ix_kg_jobs_workspace_id_created_at",
        "kg_jobs",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_kg_jobs_active_workspace_id",
        "kg_jobs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "kg_document_extractions",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("chunks_considered", sa.Integer(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column(
            "rejected_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name=op.f("ck_kg_document_extractions_status_valid"),
        ),
        _fk("kg_document_extractions", "document_id", "documents", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_document_extractions")),
        sa.UniqueConstraint(
            "document_id",
            "extractor_version",
            name=op.f("uq_kg_document_extractions_document_id_extractor_version"),
        ),
    )
    op.create_index(
        op.f("ix_kg_document_extractions_user_id"),
        "kg_document_extractions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "kg_entity_mentions",
        _id(),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("surface_text", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"entity_type IN ({ENTITY_TYPES})", name=op.f("ck_kg_entity_mentions_type_valid")
        ),
        _fk("kg_entity_mentions", "extraction_id", "kg_document_extractions", "CASCADE"),
        _fk("kg_entity_mentions", "document_id", "documents", "CASCADE"),
        _fk("kg_entity_mentions", "chunk_id", "chunks", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_entity_mentions")),
    )
    for column in ("extraction_id", "document_id", "chunk_id"):
        op.create_index(
            op.f(f"ix_kg_entity_mentions_{column}"), "kg_entity_mentions", [column], unique=False
        )

    op.create_table(
        "kg_relation_mentions",
        _id(),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("source_mention_id", sa.Uuid(), nullable=False),
        sa.Column("target_mention_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("entailment_score", sa.Float(), nullable=False),
        sa.CheckConstraint(
            f"relation_type IN ({RELATION_TYPES})",
            name=op.f("ck_kg_relation_mentions_type_valid"),
        ),
        sa.CheckConstraint(
            "source_mention_id <> target_mention_id",
            name=op.f("ck_kg_relation_mentions_not_self"),
        ),
        _fk("kg_relation_mentions", "extraction_id", "kg_document_extractions", "CASCADE"),
        _fk("kg_relation_mentions", "document_id", "documents", "CASCADE"),
        _fk("kg_relation_mentions", "chunk_id", "chunks", "CASCADE"),
        _fk("kg_relation_mentions", "source_mention_id", "kg_entity_mentions", "CASCADE"),
        _fk("kg_relation_mentions", "target_mention_id", "kg_entity_mentions", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_relation_mentions")),
    )
    for column in (
        "extraction_id",
        "document_id",
        "chunk_id",
        "source_mention_id",
        "target_mention_id",
    ):
        op.create_index(
            op.f(f"ix_kg_relation_mentions_{column}"),
            "kg_relation_mentions",
            [column],
            unique=False,
        )

    op.create_table(
        "kg_graphs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("built_by_job_id", sa.Uuid(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fingerprint", sa.Text(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        _fk("kg_graphs", "workspace_id", "workspaces", "CASCADE"),
        _fk("kg_graphs", "built_by_job_id", "kg_jobs", "SET NULL"),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_kg_graphs")),
    )
    op.create_index(op.f("ix_kg_graphs_user_id"), "kg_graphs", ["user_id"], unique=False)

    op.create_table(
        "kg_nodes",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"entity_type IN ({ENTITY_TYPES})", name=op.f("ck_kg_nodes_type_valid")),
        _fk("kg_nodes", "workspace_id", "workspaces", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_nodes")),
        sa.UniqueConstraint(
            "workspace_id",
            "entity_type",
            "normalized_key",
            name=op.f("uq_kg_nodes_workspace_id_entity_type_normalized_key"),
        ),
    )
    op.create_index(op.f("ix_kg_nodes_user_id"), "kg_nodes", ["user_id"], unique=False)

    op.create_table(
        "kg_edges",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_node_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"relation_type IN ({RELATION_TYPES})", name=op.f("ck_kg_edges_type_valid")
        ),
        _fk("kg_edges", "workspace_id", "workspaces", "CASCADE"),
        _fk("kg_edges", "source_node_id", "kg_nodes", "CASCADE"),
        _fk("kg_edges", "target_node_id", "kg_nodes", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_edges")),
        sa.UniqueConstraint(
            "workspace_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            name=op.f("uq_kg_edges_endpoints_relation_type"),
        ),
    )
    for column in ("user_id", "source_node_id", "target_node_id"):
        op.create_index(op.f(f"ix_kg_edges_{column}"), "kg_edges", [column], unique=False)

    op.create_table(
        "kg_node_mentions",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("mention_id", sa.Uuid(), nullable=False),
        _fk("kg_node_mentions", "node_id", "kg_nodes", "CASCADE"),
        _fk("kg_node_mentions", "mention_id", "kg_entity_mentions", "CASCADE"),
        sa.PrimaryKeyConstraint("node_id", "mention_id", name=op.f("pk_kg_node_mentions")),
    )
    op.create_index(
        op.f("ix_kg_node_mentions_mention_id"), "kg_node_mentions", ["mention_id"], unique=False
    )

    op.create_table(
        "kg_edge_mentions",
        sa.Column("edge_id", sa.Uuid(), nullable=False),
        sa.Column("relation_mention_id", sa.Uuid(), nullable=False),
        _fk("kg_edge_mentions", "edge_id", "kg_edges", "CASCADE"),
        _fk("kg_edge_mentions", "relation_mention_id", "kg_relation_mentions", "CASCADE"),
        sa.PrimaryKeyConstraint("edge_id", "relation_mention_id", name=op.f("pk_kg_edge_mentions")),
    )
    op.create_index(
        op.f("ix_kg_edge_mentions_relation_mention_id"),
        "kg_edge_mentions",
        ["relation_mention_id"],
        unique=False,
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Drop the tables (their indexes go with them), dependents first."""
    for table in reversed(TABLES):
        op.drop_table(table)
