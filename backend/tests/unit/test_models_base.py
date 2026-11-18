import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base
from app.models.base import NAMING_CONVENTION
from app.models.migration_scope import CHECKPOINT_TABLES, include_name


def ddl(element: CreateTable | CreateIndex) -> str:
    return str(element.compile(dialect=postgresql.dialect()))


def test_base_metadata_uses_the_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_naming_convention_names_every_constraint_and_index() -> None:
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    Table("workspaces", metadata, Column("id", Integer, primary_key=True))
    documents = Table(
        "documents",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workspace_id", Integer, ForeignKey("workspaces.id")),
        Column("content_hash", Text),
        Column("status", Text),
        UniqueConstraint("workspace_id", "content_hash"),
        CheckConstraint("status <> ''", name="status_not_empty"),
    )
    index = Index(None, documents.c.workspace_id, documents.c.status)

    table_ddl = ddl(CreateTable(documents))

    assert "CONSTRAINT pk_documents PRIMARY KEY" in table_ddl
    assert "CONSTRAINT fk_documents_workspace_id_workspaces FOREIGN KEY" in table_ddl
    assert "CONSTRAINT uq_documents_workspace_id_content_hash UNIQUE" in table_ddl
    assert "CONSTRAINT ck_documents_status_not_empty CHECK" in table_ddl
    assert ddl(CreateIndex(index)).startswith("CREATE INDEX ix_documents_workspace_id_status ")


def test_long_generated_names_fit_postgres_identifier_limit() -> None:
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    table = Table(
        "a_rather_long_table_name_for_testing",
        metadata,
        Column("first_long_column_name", Integer),
        Column("second_long_column_name", Integer),
    )
    index = Index(None, table.c.first_long_column_name, table.c.second_long_column_name)

    name = ddl(CreateIndex(index)).split()[2]

    assert len(name) <= 63
    assert name.startswith("ix_a_rather_long_table_name_for_testing_")


@pytest.mark.parametrize("schema", ["auth", "storage", "extensions", "realtime", "vault"])
def test_scope_excludes_supabase_schemas(schema: str) -> None:
    assert not include_name(schema, "schema", {})
    assert not include_name("users", "table", {"schema_name": schema})


@pytest.mark.parametrize("schema", [None, "public"])
def test_scope_includes_the_default_schema(schema: str | None) -> None:
    assert include_name(schema, "schema", {})
    assert include_name("documents", "table", {"schema_name": schema})


@pytest.mark.parametrize("table", sorted(CHECKPOINT_TABLES))
def test_scope_excludes_langgraph_checkpoint_tables(table: str) -> None:
    assert not include_name(table, "table", {"schema_name": None})
    assert not include_name(table, "table", {"schema_name": "public"})


def test_scope_keeps_columns_and_indexes_of_included_tables() -> None:
    parents = {"schema_name": None, "table_name": "documents"}
    assert include_name("status", "column", parents)
    assert include_name("ix_documents_status", "index", parents)
