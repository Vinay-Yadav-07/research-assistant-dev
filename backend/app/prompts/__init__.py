"""Versioned prompt files: `app/prompts/<kind>/<name>.<version>.md` (never edited once used)."""

from functools import cache
from pathlib import Path
from typing import Literal

PromptKind = Literal["agents", "services"]

_ROOT = Path(__file__).parent


@cache
def load_prompt(kind: PromptKind, name: str, version: str) -> str:
    """The text of one prompt version; raises `FileNotFoundError` if it does not exist."""
    path = _ROOT / kind / f"{name}.{version}.md"
    return path.read_text(encoding="utf-8").strip()
