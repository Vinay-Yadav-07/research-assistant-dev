"""Real Supabase Auth tokens against the API: JWKS verification and cross-user isolation.

Needs the Supabase dev project and two confirmed test users (docs/SETUP.md). Settings come from
`backend/.env` or the environment and are never committed:
SUPABASE_URL, DATABASE_URL, SUPABASE_PUBLISHABLE_KEY,
TEST_USER_A_EMAIL / TEST_USER_A_PASSWORD, TEST_USER_B_EMAIL / TEST_USER_B_PASSWORD.
"""

import json
import urllib.request
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


class AuthTestSettings(BaseSettings):
    """Test-only credentials; the app itself never reads these."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_publishable_key: SecretStr | None = None
    test_user_a_email: str | None = None
    test_user_a_password: SecretStr | None = None
    test_user_b_email: str | None = None
    test_user_b_password: SecretStr | None = None


def sign_in(supabase_url: str, api_key: str, email: str, password: str) -> str:
    """Password sign-in through Supabase Auth; returns the access token."""
    request = urllib.request.Request(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"apikey": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        token: str = json.load(response)["access_token"]
        return token


@pytest.fixture(scope="module")
def tokens() -> tuple[str, str]:
    settings = Settings()
    creds = AuthTestSettings()
    if (
        settings.supabase_url is None
        or creds.supabase_publishable_key is None
        or creds.test_user_a_email is None
        or creds.test_user_a_password is None
        or creds.test_user_b_email is None
        or creds.test_user_b_password is None
    ):
        pytest.skip("Supabase test users are not configured (see docs/SETUP.md)")
    key = creds.supabase_publishable_key.get_secret_value()
    return (
        sign_in(
            settings.supabase_url,
            key,
            creds.test_user_a_email,
            creds.test_user_a_password.get_secret_value(),
        ),
        sign_in(
            settings.supabase_url,
            key,
            creds.test_user_b_email,
            creds.test_user_b_password.get_secret_value(),
        ),
    )


@pytest.fixture
def api() -> Iterator[TestClient]:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL is not set")
    with TestClient(create_app(settings)) as client:
        yield client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_real_tokens_and_cross_user_isolation(api: TestClient, tokens: tuple[str, str]) -> None:
    alice, bob = tokens
    created = api.post("/api/v1/workspaces", json={"name": "auth-integration"}, headers=auth(alice))
    assert created.status_code == 201, created.text
    url = f"/api/v1/workspaces/{created.json()['id']}"
    try:
        assert api.get(url, headers=auth(alice)).status_code == 200
        assert api.get(url, headers=auth(bob)).status_code == 404
        assert api.patch(url, json={"name": "taken"}, headers=auth(bob)).status_code == 404
        assert api.delete(url, headers=auth(bob)).status_code == 404
        bob_ids = [w["id"] for w in api.get("/api/v1/workspaces", headers=auth(bob)).json()]
        assert created.json()["id"] not in bob_ids
        assert api.get(url, headers=auth(alice)).json()["name"] == "auth-integration"
    finally:
        assert api.delete(url, headers=auth(alice)).status_code == 204
    assert api.get(url, headers=auth(alice)).status_code == 404


def test_tampered_real_token_is_401(api: TestClient, tokens: tuple[str, str]) -> None:
    header, payload, signature = tokens[0].split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"

    response = api.get("/api/v1/workspaces", headers=auth(tampered))

    assert response.status_code == 401
