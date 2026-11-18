"""Alembic environment: async SQLAlchemy + psycopg, configured from app settings (D-041)."""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import Settings, get_settings
from app.models import Base
from app.models.migration_scope import include_name
from app.repositories.database import create_engine_from_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _settings() -> Settings:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to backend/.env or the environment "
            "(postgresql+psycopg://, Supabase session pooler) and run Alembic from backend/."
        )
    return settings


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_name=include_name,
        include_schemas=False,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout (`alembic upgrade head --sql`) without connecting."""
    database_url = _settings().database_url
    assert database_url is not None
    _configure(
        url=database_url.get_secret_value(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations over the same async engine configuration the app uses."""
    engine = create_engine_from_settings(_settings())
    assert engine is not None
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
