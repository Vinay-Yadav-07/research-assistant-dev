"""Create or migrate the LangGraph checkpoint tables in the `langgraph` schema.

Run after `alembic upgrade head` (migration 0005 creates the schema) and after every langgraph
upgrade; it is idempotent. The app never runs it at startup. From `backend/`:
`uv run python -m scripts.setup_checkpointer`.
"""

import asyncio
import sys

from app.core.config import get_settings
from app.repositories.checkpoints import setup_checkpoint_tables


def main() -> None:
    """Set up the tables against `DATABASE_URL` and print them."""
    settings = get_settings()
    if settings.database_url is None:
        sys.exit("DATABASE_URL is not set.")
    tables = asyncio.run(setup_checkpoint_tables(settings.database_url.get_secret_value()))
    print(f"Checkpoint tables (RLS enabled): {', '.join(tables)}")


if __name__ == "__main__":
    main()
