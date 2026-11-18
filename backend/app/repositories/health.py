"""Database connectivity check."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseHealthRepository:
    """Runs a trivial query to prove the database is reachable."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ping(self) -> None:
        """Execute `SELECT 1`; raises if the database cannot be reached."""
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
