"""LangSmith tracing setup (FR-28, NFR-07).

LangChain and LangGraph read the `LANGSMITH_*` environment variables, so settings are copied
there once at startup. Tracing is written explicitly as off when disabled, so a stray shell
variable cannot send traces the settings did not ask for.
"""

import os

from app.core.config import Settings


def configure_tracing(settings: Settings) -> None:
    """Make the process environment match the LangSmith settings."""
    if settings.langsmith_tracing and settings.langsmith_api_key is not None:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ.pop("LANGSMITH_API_KEY", None)
