"""Domain models: tables, constraints, and indexes as SRS §14.1 and the retrieval design need."""

import pytest
from sqlalchemy import CheckConstraint, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.core.config import Settings
from app.models import (
    AgentRun,
    Approval,
    Base,
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Conversation,
    Document,
    EvalResult,
    EvalRun,
    Evidence,
    KGDocumentExtraction,
    KGEdge,
    KGEdgeMention,
    KGEntityMention,
    KGGraph,
    KGJob,
    KGNode,
    KGNodeMention,
    KGRelationMention,
    Message,
    ResearchGap,
    SavedFinding,
    TopicProfile,
    Workspace,
    WorkspaceDocument,
)
from app.models._types import EMBEDDING_DIMENSION, one_of
from app.models.conversation import CLAIM_STATUSES, MESSAGE_MODES
from app.models.document import DOCUMENT_STATUSES
from app.models.knowledge_graph import ENTITY_TYPES, RELATION_TYPES
from app.models.workspace import KNOWLEDGE_MODES


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def check_names(name: str) -> set[str]:
    return {str(c.name) for c in table(name).constraints if isinstance(c, CheckConstraint)}


def index_ddl(table_name: str, index_name: str) -> str:
    [index] = [i for i in table(table_name).indexes if i.name == index_name]
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_metadata_has_the_phase_1_2_and_4_and_knowledge_graph_tables() -> None:
    assert set(Base.metadata.tables) == {
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
    models = (
        Workspace,
        Document,
        WorkspaceDocument,
        Chunk,
        TopicProfile,
        Conversation,
        Message,
        Claim,
        Evidence,
        Citation,
        Approval,
        AgentRun,
        EvalRun,
        EvalResult,
        SavedFinding,
        Contradiction,
        ResearchGap,
        KGJob,
        KGDocumentExtraction,
        KGEntityMention,
        KGRelationMention,
        KGGraph,
        KGNode,
        KGEdge,
        KGNodeMention,
        KGEdgeMention,
    )
    assert {model.__tablename__ for model in models} == set(Base.metadata.tables)


def test_embedding_columns_match_the_configured_dimension(clean_env: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).embedding_dimension == EMBEDDING_DIMENSION
    assert table("chunks").c.embedding.type.dim == EMBEDDING_DIMENSION
    assert table("topic_profiles").c.centroid_embedding.type.dim == EMBEDDING_DIMENSION


def test_every_timestamp_is_timezone_aware() -> None:
    timestamps = [
        column
        for t in Base.metadata.tables.values()
        for column in t.columns
        if column.name.endswith("_at")
    ]

    assert timestamps
    assert all(column.type.timezone for column in timestamps)  # type: ignore[attr-defined]


def test_user_owned_tables_index_user_id() -> None:
    assert index_ddl("workspaces", "ix_workspaces_user_id").endswith("(user_id)")
    [unique] = [
        c for c in table("documents").constraints if c.name == "uq_documents_user_id_content_hash"
    ]
    assert [column.name for column in unique.columns] == ["user_id", "content_hash"]
    for name in (
        "conversations",
        "approvals",
        "agent_runs",
        "saved_findings",
        "contradictions",
        "research_gaps",
        "kg_jobs",
        "kg_document_extractions",
        "kg_graphs",
        "kg_nodes",
        "kg_edges",
    ):
        assert index_ddl(name, f"ix_{name}_user_id").endswith("(user_id)")


def test_history_lists_have_composite_indexes() -> None:
    assert index_ddl("messages", "ix_messages_conversation_id_created_at").endswith(
        "(conversation_id, created_at)"
    )
    assert index_ddl("conversations", "ix_conversations_workspace_id_updated_at").endswith(
        "(workspace_id, updated_at)"
    )
    for name in ("saved_findings", "contradictions", "research_gaps"):
        assert index_ddl(name, f"ix_{name}_workspace_id_created_at").endswith(
            "(workspace_id, created_at)"
        )


def test_chunks_have_hnsw_cosine_and_gin_full_text_indexes() -> None:
    assert index_ddl("chunks", "ix_chunks_embedding") == (
        "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    assert index_ddl("chunks", "ix_chunks_tsv") == (
        "CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)"
    )


def test_chunk_tsv_is_a_stored_generated_column() -> None:
    computed = table("chunks").c.tsv.computed

    assert computed is not None
    assert computed.persisted is True
    assert "to_tsvector('english'::regconfig" in str(computed.sqltext)


def test_links_and_children_cascade_on_delete() -> None:
    foreign_keys = [
        fk
        for name in ("workspace_documents", "chunks", "topic_profiles")
        for fk in table(name).foreign_keys
    ]

    assert len(foreign_keys) == 4
    assert all(fk.ondelete == "CASCADE" for fk in foreign_keys)


def test_chat_history_cascades_from_the_workspace() -> None:
    def ondelete(table_name: str, column: str) -> str | None:
        [fk] = table(table_name).c[column].foreign_keys
        return fk.ondelete

    for table_name, column in [
        ("conversations", "workspace_id"),
        ("messages", "conversation_id"),
        ("claims", "message_id"),
        ("evidence", "claim_id"),
        ("citations", "claim_id"),
        ("approvals", "conversation_id"),
        ("agent_runs", "workspace_id"),
        ("agent_runs", "conversation_id"),
        ("eval_results", "eval_run_id"),
        ("saved_findings", "workspace_id"),
        ("contradictions", "workspace_id"),
        ("research_gaps", "workspace_id"),
    ]:
        assert ondelete(table_name, column) == "CASCADE", (table_name, column)


def test_history_survives_deleted_sources_and_runs() -> None:
    nullable_links = [
        ("evidence", "chunk_id"),
        ("citations", "chunk_id"),
        ("citations", "document_id"),
        ("messages", "run_id"),
        ("approvals", "run_id"),
    ]
    for table_name, column in nullable_links:
        [fk] = table(table_name).c[column].foreign_keys
        assert fk.ondelete == "SET NULL", (table_name, column)
        assert table(table_name).c[column].nullable
        # Indexed, so deleting a document does not scan the whole history table.
        assert index_ddl(table_name, f"ix_{table_name}_{column}").endswith(f"({column})")


def test_citations_keep_a_snapshot_of_their_source() -> None:
    columns = set(table("citations").c.keys())

    assert {"document_title", "page_start", "page_end", "section", "quote"} <= columns


def test_named_check_constraints() -> None:
    assert check_names("workspaces") == {"ck_workspaces_default_mode_valid"}
    assert check_names("documents") == {"ck_documents_source_valid", "ck_documents_status_valid"}
    assert check_names("chunks") == {"ck_chunks_page_range_valid"}
    assert check_names("conversations") == {"ck_conversations_mode_valid"}
    assert check_names("messages") == {"ck_messages_role_valid", "ck_messages_mode_valid"}
    assert check_names("claims") == {"ck_claims_status_valid"}
    assert check_names("citations") == {
        "ck_citations_source_type_valid",
        "ck_citations_page_range_valid",
    }
    assert check_names("approvals") == {"ck_approvals_decision_valid"}
    assert check_names("agent_runs") == {"ck_agent_runs_status_valid"}
    assert check_names("saved_findings") == {"ck_saved_findings_type_valid"}
    assert check_names("contradictions") == {"ck_contradictions_label_valid"}
    assert check_names("research_gaps") == {"ck_research_gaps_scope_valid"}


def test_modes_and_claim_statuses_follow_the_srs() -> None:
    assert MESSAGE_MODES == ("corpus_only", "corpus_web", "general_knowledge")
    assert set(KNOWLEDGE_MODES) < set(MESSAGE_MODES)
    assert CLAIM_STATUSES == ("supported", "partially_supported", "unsupported", "uncertain")


def test_one_of_builds_an_in_list() -> None:
    assert one_of("status", DOCUMENT_STATUSES) == (
        "status IN ('uploaded', 'parsing', 'embedding', 'ready', 'failed')"
    )


def test_a_workspace_has_at_most_one_active_knowledge_graph_job() -> None:
    assert index_ddl("kg_jobs", "uq_kg_jobs_active_workspace_id") == (
        "CREATE UNIQUE INDEX uq_kg_jobs_active_workspace_id ON kg_jobs (workspace_id) "
        "WHERE status IN ('queued', 'running')"
    )


def test_knowledge_graph_evidence_cascades_from_documents_and_chunks() -> None:
    def ondelete(table_name: str, column: str) -> str | None:
        [fk] = table(table_name).c[column].foreign_keys
        return fk.ondelete

    for name in ("kg_entity_mentions", "kg_relation_mentions"):
        assert ondelete(name, "document_id") == "CASCADE"
        assert ondelete(name, "chunk_id") == "CASCADE"
        assert ondelete(name, "extraction_id") == "CASCADE"
    assert ondelete("kg_document_extractions", "document_id") == "CASCADE"
    for name in ("kg_jobs", "kg_graphs", "kg_nodes", "kg_edges"):
        assert ondelete(name, "workspace_id") == "CASCADE"
    assert ondelete("kg_jobs", "current_document_id") == "SET NULL"
    assert ondelete("kg_graphs", "built_by_job_id") == "SET NULL"


def test_knowledge_graph_vocabulary_follows_the_srs() -> None:
    assert check_names("kg_entity_mentions") == {"ck_kg_entity_mentions_type_valid"}
    assert check_names("kg_relation_mentions") == {
        "ck_kg_relation_mentions_type_valid",
        "ck_kg_relation_mentions_not_self",
    }
    assert check_names("kg_jobs") == {
        "ck_kg_jobs_kind_valid",
        "ck_kg_jobs_status_valid",
        "ck_kg_jobs_phase_valid",
    }
    assert ENTITY_TYPES == ("concept", "method", "dataset", "metric", "task", "tool", "finding")
    assert RELATION_TYPES == (
        "uses",
        "evaluated_on",
        "measured_by",
        "addresses",
        "compared_with",
        "reports",
    )
