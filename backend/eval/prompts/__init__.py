"""Versioned prompts of the baseline conditions: `eval/prompts/<name>.<version>.md`.

They live here, not in `app/prompts/`, because only the evaluation uses them.
"""

from functools import cache
from pathlib import Path

_ROOT = Path(__file__).parent


@cache
def load_prompt(name: str, version: str) -> str:
    """The text of one prompt version; raises `FileNotFoundError` if it does not exist."""
    return (_ROOT / f"{name}.{version}.md").read_text(encoding="utf-8").strip()
