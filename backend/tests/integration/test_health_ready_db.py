"""Readiness against the real Supabase dev database. Run with `uv run pytest -m integration`."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_ready_reports_database_reachable() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not set (backend/.env or environment)")

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
