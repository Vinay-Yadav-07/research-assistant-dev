"""Migrations against the real Supabase dev database. Run with `uv run pytest -m integration`.

Needs `uv run alembic upgrade head` first; this test only reads the database.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import Settings

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_database_is_at_head_and_matches_models() -> None:
    if Settings().database_url is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")

    # Raises if the database is not at head or autogenerate finds any difference.
    command.check(Config(str(ALEMBIC_INI)))
