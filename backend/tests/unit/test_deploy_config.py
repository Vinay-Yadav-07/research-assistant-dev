"""Checks that the Docker/Space deploy files agree with the project configuration."""

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DOCKERFILE = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
DOWNLOAD = "ENVIRONMENT=local python -m scripts.download_models"


def test_dockerfile_uv_matches_required_version() -> None:
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    required = pyproject["tool"]["uv"]["required-version"].removeprefix("==")

    tags = re.findall(r"ghcr\.io/astral-sh/uv:(\S+)", DOCKERFILE)

    assert tags == [required]


def test_dockerfile_python_matches_python_version_file() -> None:
    python_version = (BACKEND / ".python-version").read_text(encoding="utf-8").strip()

    match = re.search(r"^FROM python:(\d+\.\d+)\.", DOCKERFILE, re.MULTILINE)

    assert match is not None
    assert match.group(1) == python_version


def test_dockerfile_runs_as_space_user() -> None:
    assert re.search(r"^USER 1000$", DOCKERFILE, re.MULTILINE)


def test_dockerfile_port_matches_space_app_port() -> None:
    readme = (BACKEND / "README.md").read_text(encoding="utf-8")
    front_matter = readme.split("---")[1]
    app_port = re.search(r"^app_port: (\d+)$", front_matter, re.MULTILINE)

    assert app_port is not None
    assert re.search(rf"^EXPOSE {app_port.group(1)}$", DOCKERFILE, re.MULTILINE)
    assert f'"--port", "{app_port.group(1)}"' in DOCKERFILE
    assert re.search(r"^sdk: docker$", front_matter, re.MULTILINE)


def test_dockerfile_bakes_models_and_runs_them_offline() -> None:
    download = DOCKERFILE.index(DOWNLOAD)
    offline = DOCKERFILE.index("ENV HF_HUB_OFFLINE=1")

    assert download < offline
    for setting in (
        "PRELOAD_MODELS=true",
        "EMBEDDING_PROVIDER=sentence_transformers",
        "RERANKER_PROVIDER=cross_encoder",
        "NLI_PROVIDER=cross_encoder",
    ):
        assert re.search(rf"^\s+{setting}\b", DOCKERFILE[:download], re.MULTILINE), setting


def test_dockerfile_build_steps_run_as_local_and_runtime_as_prod() -> None:
    """Space secrets are missing at build time, so prod settings validation would fail there."""
    settings_runs = [
        line
        for line in DOCKERFILE.splitlines()
        if "scripts.download_models" in line or "get_settings()" in line
    ]

    assert settings_runs
    assert all("ENVIRONMENT=local python" in line for line in settings_runs)
    assert "ARG DOWNLOAD_MODELS=true" in DOCKERFILE
    assert re.search(r"^\s+ENVIRONMENT=prod\b", DOCKERFILE, re.MULTILINE)
    assert "ENV ENVIRONMENT=local" not in DOCKERFILE


def test_dockerfile_uses_the_real_pdf_parser() -> None:
    assert re.search(r"^\s+PARSER_PROVIDER=pymupdf4llm\b", DOCKERFILE, re.MULTILINE)


def test_dockerfile_uses_hosted_llms_so_prod_never_answers_with_the_fake() -> None:
    """The fake LLM is the config default; prod must not fall back to it silently."""
    assert re.search(r"^\s+LLM_FAST_PROVIDER=groq\b", DOCKERFILE, re.MULTILINE)
    assert re.search(r"^\s+LLM_STRONG_PROVIDER=gemini\b", DOCKERFILE, re.MULTILINE)
    assert "API_KEY" not in DOCKERFILE


def test_dockerfile_model_layer_copies_only_what_download_needs() -> None:
    download = DOCKERFILE.index(DOWNLOAD)
    copied = re.findall(r"^COPY (?!--from)(.+) \S+$", DOCKERFILE[:download], re.MULTILINE)
    sources = {path for line in copied for path in line.split()}

    assert "app" not in sources
    assert "app/core/config.py" in sources
    assert "scripts/download_models.py" in sources


def test_dockerfile_ships_the_benchmark_scripts() -> None:
    assert re.search(r"^COPY scripts \./scripts$", DOCKERFILE, re.MULTILINE)
