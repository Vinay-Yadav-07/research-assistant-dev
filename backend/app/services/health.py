"""Readiness check for the service's dependencies."""

import asyncio
import logging
from typing import Protocol

from app.schemas.health import DatabaseStatus, ReadinessChecks, ReadinessResponse

logger = logging.getLogger(__name__)


class DatabasePinger(Protocol):
    """Anything that can prove the database is reachable."""

    async def ping(self) -> None: ...


class ReadinessService:
    """Checks dependencies and reports whether the service is ready for traffic."""

    def __init__(self, database: DatabasePinger | None, *, timeout_seconds: float) -> None:
        self._database = database
        self._timeout_seconds = timeout_seconds

    async def check(self) -> ReadinessResponse:
        """Run all dependency checks. Failure reasons are logged, never returned."""
        database = await self._check_database()
        return ReadinessResponse(
            status="ready" if database == "ok" else "not_ready",
            checks=ReadinessChecks(database=database),
        )

    async def _check_database(self) -> DatabaseStatus:
        if self._database is None:
            return "not_configured"
        try:
            await asyncio.wait_for(self._database.ping(), timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning("Database readiness check timed out after %ss", self._timeout_seconds)
            return "unavailable"
        except Exception:
            logger.warning("Database readiness check failed", exc_info=True)
            return "unavailable"
        return "ok"
