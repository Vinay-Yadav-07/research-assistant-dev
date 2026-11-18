"""Experiment log: every measurement script writes one JSON file to `docs/experiments/`.

Each file records the date, git commit, models, an allow-list of settings (never the whole
`Settings`, so no secret can leak), the dataset, the hardware, per-item raw results, and the
summary metrics. Before writing, the JSON text is checked for secret values (every `SecretStr`
in the settings plus any values the caller passes, such as an access token); a match raises.
"""

import json
import os
import platform
import subprocess
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR = REPO_ROOT / "docs/experiments"
SNIPPET_CHARS = 200

# Settings that describe an experiment. Add a name here to record it; nothing else is written.
RECORDED_SETTINGS = (
    "embedding_provider",
    "embedding_model",
    "embedding_dimension",
    "embedding_batch_size",
    "reranker_provider",
    "reranker_model",
    "reranker_max_length",
    "reranker_batch_size",
    "nli_provider",
    "nli_model",
    "nli_max_length",
    "nli_batch_size",
    "parser_provider",
    "dense_top_k",
    "lexical_top_k",
    "rrf_k",
    "rerank_candidates",
    "retrieval_top_k",
    "sufficiency_fast_pass_score",
    "sufficiency_check_chunks",
    "llm_strong_provider",
    "llm_strong_model",
    "chunk_min_tokens",
    "chunk_max_tokens",
    "chunk_overlap_ratio",
    "chunk_merge_below_tokens",
    "chunk_hard_max_tokens",
    "compatibility_chunks",
    "compatibility_max_pages",
    "compatibility_threshold",
    "ingestion_concurrency",
    "local_inference_concurrency",
    "eval_judge_provider",
    "eval_judge_model",
    "eval_answer_relevancy_strictness",
    "llm_graph_provider",
    "llm_graph_model",
    "kg_min_chunk_words",
    "kg_max_chunks_per_paper",
    "kg_chunks_per_call",
    "kg_max_output_tokens",
    "kg_relation_entailment_score",
    "kg_relation_contradiction_score",
)


class SecretInExperimentError(ValueError):
    """The experiment JSON would contain a secret value."""


def recorded_settings(settings: Settings) -> dict[str, Any]:
    """The allow-listed settings, by name."""
    return {name: getattr(settings, name) for name in RECORDED_SETTINGS}


def snippet(text: str) -> str:
    """Text shortened to at most SNIPPET_CHARS characters, so no long paper text is committed."""
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1] + "…"


def git_commit(cwd: Path = REPO_ROOT) -> tuple[str, bool]:
    """(HEAD SHA, working tree has uncommitted changes); ("unknown", False) without git."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", False
    return sha, bool(status.strip())


def hardware() -> dict[str, Any]:
    """CPU count, platform, and torch threads (only if torch is already imported)."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
    torch = sys.modules.get("torch")
    info["torch_threads"] = torch.get_num_threads() if torch is not None else None
    return info


def secret_values(settings: Settings, extra: Iterable[str | None] = ()) -> list[str]:
    """Every non-empty `SecretStr` value in `settings`, plus `extra`."""
    values = [
        value.get_secret_value()
        for value in (getattr(settings, name) for name in type(settings).model_fields)
        if isinstance(value, SecretStr)
    ]
    return [value for value in [*values, *extra] if value]


def write_experiment(
    name: str,
    *,
    settings: Settings,
    models: Mapping[str, Any],
    dataset: str,
    results: list[dict[str, Any]],
    summary: Mapping[str, Any],
    parameters: Mapping[str, Any] | None = None,
    hardware_extra: Mapping[str, Any] | None = None,
    secrets: Iterable[str | None] = (),
    directory: Path | None = None,
) -> Path:
    """Write the experiment JSON and return its path.

    `parameters` holds script-specific options (e.g. candidates reranked); `secrets` holds extra
    values that must not appear (e.g. an access token). Raises `SecretInExperimentError` instead
    of writing if any secret value appears in the JSON text.
    """
    now = datetime.now(UTC)
    sha, dirty = git_commit()
    record = {
        "experiment": name,
        "date": now.isoformat(timespec="seconds"),
        "git_commit": sha,
        "git_dirty": dirty,
        "models": dict(models),
        "settings": recorded_settings(settings),
        "parameters": dict(parameters or {}),
        "dataset": dataset,
        "hardware": {**hardware(), **(hardware_extra or {})},
        "results": results,
        "summary": dict(summary),
    }
    text = json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n"
    for value in secret_values(settings, secrets):
        if value in text:
            raise SecretInExperimentError(f"experiment {name!r} would contain a secret value")
    directory = directory or EXPERIMENTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{now:%Y-%m-%dT%H%M%SZ}_{name}_{sha[:7]}.json"
    path.write_text(text, encoding="utf-8")
    return path
