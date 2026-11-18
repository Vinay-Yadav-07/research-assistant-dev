import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_readiness_service
from app.services.health import ReadinessService


class StubDatabase:
    def __init__(self, *, error: Exception | None = None, delay: float = 0.0) -> None:
        self.error = error
        self.delay = delay
        self.calls = 0

    async def ping(self) -> None:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error


def use_database(app: FastAPI, database: StubDatabase, timeout: float = 1.0) -> None:
    service = ReadinessService(database, timeout_seconds=timeout)
    app.dependency_overrides[get_readiness_service] = lambda: service


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_health_does_not_touch_the_database(app: FastAPI, client: TestClient) -> None:
    database = StubDatabase()
    use_database(app, database)

    client.get("/api/v1/health")

    assert database.calls == 0


def test_ready_without_database_url_is_not_configured(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "not_configured"}}


def test_ready_when_database_reachable(app: FastAPI, client: TestClient) -> None:
    database = StubDatabase()
    use_database(app, database)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    assert database.calls == 1


def test_ready_when_database_fails_hides_the_reason(app: FastAPI, client: TestClient) -> None:
    use_database(app, StubDatabase(error=ConnectionError("password=hunter2 refused")))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    assert "hunter2" not in response.text


def test_ready_when_database_times_out(app: FastAPI, client: TestClient) -> None:
    use_database(app, StubDatabase(delay=5.0), timeout=0.05)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_openapi_documents_health_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    health = paths["/api/v1/health"]["get"]
    ready = paths["/api/v1/health/ready"]["get"]
    assert health["operationId"] == "getHealth"
    assert ready["operationId"] == "getReadiness"
    ready_schema = "#/components/schemas/ReadinessResponse"
    for code in ("200", "503"):
        assert ready["responses"][code]["content"]["application/json"]["schema"]["$ref"] == (
            ready_schema
        )
