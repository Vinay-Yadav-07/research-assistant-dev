"""Unit tests never read `backend/.env` or config variables from the shell, so local and CI runs
see the same settings. Integration tests (tests/integration/) still read them."""

from collections.abc import Iterator

import pytest

from app.core.config import Settings, get_settings
from tests.conftest import CONFIG_ENV_VARS


@pytest.fixture(autouse=True)
def hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Disable the env file and remove config variables for every unit test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
