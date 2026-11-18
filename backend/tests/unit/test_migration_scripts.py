"""Checks on the migration scripts themselves; no database needed."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import Base
from app.models._types import EMBEDDING_DIMENSION
from app.models.migration_scope import CHECKPOINT_SCHEMA

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def test_config_has_no_database_url() -> None:
    assert Config(str(ALEMBIC_INI)).get_main_option("sqlalchemy.url") is None


def test_revision_history_has_a_single_head(scripts: ScriptDirectory) -> None:
    assert len(scripts.get_heads()) == 1


def test_history_starts_at_the_baseline(scripts: ScriptDirectory) -> None:
    bases = scripts.get_bases()

    assert bases == ["0001"]
    baseline = scripts.get_revision("0001")
    assert baseline is not None
    assert baseline.down_revision is None


def test_domain_migration_follows_the_baseline(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0002")

    assert revision is not None
    assert revision.down_revision == "0001"


def test_unique_content_hash_migration_follows_the_domain_migration(
    scripts: ScriptDirectory,
) -> None:
    revision = scripts.get_revision("0003")

    assert revision is not None
    assert revision.down_revision == "0002"


def test_chat_migration_follows_the_unique_hash_migration(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0004")

    assert revision is not None
    assert revision.down_revision == "0003"


def test_checkpoint_schema_migration_follows_the_chat_migration(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0005")

    assert revision is not None
    assert revision.down_revision == "0004"
    assert revision.module.SCHEMA == CHECKPOINT_SCHEMA


def test_message_clock_timestamp_migration_follows_the_checkpoint_schema(
    scripts: ScriptDirectory,
) -> None:
    revision = scripts.get_revision("0006")

    assert revision is not None
    assert revision.down_revision == "0005"


def test_research_migration_follows_the_message_timestamp_migration(
    scripts: ScriptDirectory,
) -> None:
    revision = scripts.get_revision("0007")

    assert revision is not None
    assert revision.down_revision == "0006"


def test_knowledge_graph_migration_is_the_head(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0008")

    assert revision is not None
    assert revision.down_revision == "0007"
    assert scripts.get_current_head() == "0008"


def test_checkpoint_schema_migration_never_grants(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0005")
    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")

    assert "GRANT " not in source
    assert "REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC, anon, authenticated" in source


def test_domain_migrations_create_every_model_table(scripts: ScriptDirectory) -> None:
    domain = scripts.get_revision("0002")
    chat = scripts.get_revision("0004")
    research = scripts.get_revision("0007")
    knowledge_graph = scripts.get_revision("0008")
    assert domain is not None
    assert chat is not None
    assert research is not None
    assert knowledge_graph is not None

    assert domain.module.EMBEDDING_DIMENSION == EMBEDDING_DIMENSION
    tables = (
        set(domain.module.TABLES)
        | set(chat.module.TABLES)
        | set(research.module.TABLES)
        | set(knowledge_graph.module.TABLES)
    )
    assert tables == set(Base.metadata.tables)


@pytest.mark.parametrize("revision_id", ["0004", "0007", "0008"])
def test_table_migrations_enable_rls_and_never_grant(
    scripts: ScriptDirectory, revision_id: str
) -> None:
    revision = scripts.get_revision(revision_id)
    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")

    assert "GRANT " not in source
    assert 'op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")' in source


def test_domain_migration_never_grants_client_roles(scripts: ScriptDirectory) -> None:
    revision = scripts.get_revision("0002")
    assert revision is not None
    source = Path(revision.path).read_text(encoding="utf-8")

    assert "GRANT " not in source.replace("REVOKE", "")
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
