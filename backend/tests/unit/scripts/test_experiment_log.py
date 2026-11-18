import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from scripts import experiment_log
from scripts.experiment_log import (
    RECORDED_SETTINGS,
    SNIPPET_CHARS,
    SecretInExperimentError,
    git_commit,
    snippet,
    write_experiment,
)

DATABASE_URL = "postgresql+psycopg://postgres.abc:db-password-123@pooler.example.com:5432/postgres"
SECRET_KEY = "sb_secret_0123456789abcdef"
TOKEN = "eyJhbGciOiJFUzI1NiJ9.payload.signature"


def secret_settings() -> Settings:
    return Settings(
        database_url=SecretStr(DATABASE_URL),
        supabase_secret_key=SecretStr(SECRET_KEY),
        supabase_url="https://abc.supabase.co",
        contact_email="team@example.com",
    )


def write(tmp_path: Path, **overrides: Any) -> Path:
    arguments: dict[str, Any] = {
        "settings": secret_settings(),
        "models": {"embedding": "BAAI/bge-small-en-v1.5"},
        "dataset": "questions.json",
        "results": [{"question": "q1", "rank": 1}],
        "summary": {"R@5": 1.0},
        "directory": tmp_path,
    }
    return write_experiment("demo", **{**arguments, **overrides})


def test_writes_every_field(tmp_path: Path) -> None:
    path = write(tmp_path, parameters={"candidates": 20}, hardware_extra={"server": "cpu-basic"})

    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(record) == {
        "experiment",
        "date",
        "git_commit",
        "git_dirty",
        "models",
        "settings",
        "parameters",
        "dataset",
        "hardware",
        "results",
        "summary",
    }
    assert record["experiment"] == "demo"
    assert record["dataset"] == "questions.json"
    assert record["results"] == [{"question": "q1", "rank": 1}]
    assert record["summary"] == {"R@5": 1.0}
    assert record["parameters"] == {"candidates": 20}
    assert record["hardware"]["cpu_count"] is not None
    assert record["hardware"]["server"] == "cpu-basic"
    assert re.fullmatch(r"[0-9a-f]{40}|unknown", record["git_commit"])
    assert path.name.endswith(f"_demo_{record['git_commit'][:7]}.json")


def test_settings_are_only_the_allow_list(tmp_path: Path) -> None:
    record = json.loads(write(tmp_path).read_text(encoding="utf-8"))

    assert list(record["settings"]) == list(RECORDED_SETTINGS)
    assert record["settings"]["compatibility_threshold"] == 0.83


def test_no_secret_or_connection_value_is_written(tmp_path: Path) -> None:
    text = write(tmp_path, secrets=[TOKEN]).read_text(encoding="utf-8")

    for value in (DATABASE_URL, "db-password-123", SECRET_KEY, TOKEN, "abc.supabase.co"):
        assert value not in text
    assert "team@example.com" not in text


def test_allow_list_names_no_secret_like_setting() -> None:
    secret_fields = {
        name for name, info in Settings.model_fields.items() if "SecretStr" in str(info.annotation)
    }
    assert secret_fields >= {"database_url", "supabase_secret_key"}
    for name in RECORDED_SETTINGS:
        assert name not in secret_fields
        assert not re.search(r"key|secret|_token\b|password|url|email", name), name


@pytest.mark.parametrize("leaked", [DATABASE_URL, SECRET_KEY])
def test_secret_setting_in_results_refuses_to_write(tmp_path: Path, leaked: str) -> None:
    with pytest.raises(SecretInExperimentError):
        write(tmp_path, results=[{"note": f"connected with {leaked}"}])
    assert list(tmp_path.iterdir()) == []


def test_extra_secret_in_parameters_refuses_to_write(tmp_path: Path) -> None:
    with pytest.raises(SecretInExperimentError):
        write(tmp_path, parameters={"token": TOKEN}, secrets=[TOKEN])
    assert list(tmp_path.iterdir()) == []


def test_empty_extra_secrets_are_ignored(tmp_path: Path) -> None:
    assert write(tmp_path, secrets=["", None]).exists()


def test_default_directory_is_docs_experiments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(experiment_log, "EXPERIMENTS_DIR", tmp_path / "experiments")

    path = write(tmp_path, directory=None)

    assert path.parent == tmp_path / "experiments"


def test_git_commit_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)

    assert git_commit() == ("unknown", False)


def test_snippet_is_truncated() -> None:
    assert snippet("short") == "short"
    long = snippet("x" * 1000)
    assert len(long) == SNIPPET_CHARS
    assert long.endswith("…")
