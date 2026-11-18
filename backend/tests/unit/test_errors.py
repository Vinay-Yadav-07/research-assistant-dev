from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    DependencyUnavailableError,
    ExternalServiceError,
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
)
from app.main import create_app

ERRORS: dict[str, type[AppError]] = {
    "not-found": NotFoundError,
    "permission": PermissionDeniedError,
    "invalid": InvalidInputError,
    "conflict": ConflictError,
    "external": ExternalServiceError,
    "unavailable": DependencyUnavailableError,
    "base": AppError,
}


@pytest.fixture
def error_client(settings: Settings) -> Iterator[TestClient]:
    app: FastAPI = create_app(settings)

    @app.get("/boom/{kind}")
    async def boom(kind: str) -> None:
        raise ERRORS[kind]("Something specific.", details={"id": "42"})

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/typed/{number}")
    async def typed(number: int) -> int:
        return number

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize(
    ("kind", "status_code", "code"),
    [
        ("not-found", 404, "not_found"),
        ("permission", 403, "permission_denied"),
        ("invalid", 422, "invalid_input"),
        ("conflict", 409, "conflict"),
        ("external", 502, "external_service_error"),
        ("unavailable", 503, "dependency_unavailable"),
        ("base", 500, "app_error"),
    ],
)
def test_domain_errors_map_to_status_and_envelope(
    error_client: TestClient, kind: str, status_code: int, code: str
) -> None:
    response = error_client.get(f"/boom/{kind}")

    assert response.status_code == status_code
    assert response.json() == {
        "error": {"code": code, "message": "Something specific.", "details": {"id": "42"}}
    }


def test_default_message_is_used_when_none_given() -> None:
    assert NotFoundError().message == "Resource not found."


def test_unhandled_error_returns_generic_500(error_client: TestClient) -> None:
    response = error_client.get("/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": {},
        }
    }
    assert "secret internal detail" not in response.text


def test_validation_error_uses_envelope(error_client: TestClient) -> None:
    response = error_client.get("/typed/not-a-number")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["errors"][0]["loc"] == ["path", "number"]


def test_unknown_route_uses_envelope(error_client: TestClient) -> None:
    response = error_client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"
