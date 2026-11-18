"""Database engine construction."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine_from_settings(settings: Settings) -> AsyncEngine | None:
    """Create the async engine, or return None when `DATABASE_URL` is not configured.

    Engine creation is lazy: no connection is opened until the first query.
    """
    if settings.database_url is None:
        return None
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            # Server-side prepared statements break behind PgBouncer-style poolers.
            "prepare_threshold": None,
        },
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions whose objects stay readable after commit (responses are built from them)."""
    return async_sessionmaker(engine, expire_on_commit=False)
