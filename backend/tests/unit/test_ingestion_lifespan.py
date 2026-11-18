"""The app runs the stale-ingestion sweep at startup and then periodically (D-058)."""

import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from app.services.ingestion import IngestionService

# Nothing listens on port 1, so every sweep fails fast with a connection error.
UNREACHABLE_DB = SecretStr("postgresql+psycopg://user:pw@127.0.0.1:1/db")


def test_sweep_runs_periodically_and_stops_on_shutdown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []
    real_fail_stale = IngestionService.fail_stale

    async def counted(self: IngestionService) -> int:
        calls.append(time.monotonic())
        return await real_fail_stale(self)  # raises: the database is unreachable

    monkeypatch.setattr(IngestionService, "fail_stale", counted)
    app = create_app(
        settings.model_copy(
            update={"database_url": UNREACHABLE_DB, "ingestion_sweep_interval_minutes": 0.0005}
        )
    )

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200  # sweep errors never block startup
        deadline = time.monotonic() + 5
        while len(calls) < 4:  # startup + at least 3 periodic sweeps, each failing
            assert time.monotonic() < deadline, f"only {len(calls)} sweeps"
            time.sleep(0.02)

    after_shutdown = len(calls)
    time.sleep(0.15)
    assert len(calls) == after_shutdown


def test_no_sweep_without_a_database(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app):
        assert app.state.ingestion is None
