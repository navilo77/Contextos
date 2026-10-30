from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL_ENV: Final = "CONTEXT_OS_DATABASE_URL"
DATABASE_HOST_ENV: Final = "CONTEXT_OS_DATABASE_HOST"
DATABASE_PORT_ENV: Final = "CONTEXT_OS_DATABASE_PORT"
DATABASE_USER_ENV: Final = "CONTEXT_OS_DATABASE_USER"
DATABASE_PASSWORD_ENV: Final = "CONTEXT_OS_DATABASE_PASSWORD"
DATABASE_NAME_ENV: Final = "CONTEXT_OS_DATABASE_NAME"


class DatabaseConfigurationError(RuntimeError):
    """Raised when the required PostgreSQL connection configuration is invalid."""


def database_url_from_env() -> URL:
    raw_url = os.getenv(DATABASE_URL_ENV, "")
    if raw_url:
        try:
            url = make_url(raw_url)
        except (ArgumentError, ValueError) as exc:
            raise DatabaseConfigurationError(
                f"{DATABASE_URL_ENV} must be a valid PostgreSQL connection URL."
            ) from exc
        return _validate_database_url(url)

    components = {
        "host": os.getenv(DATABASE_HOST_ENV, ""),
        "port": os.getenv(DATABASE_PORT_ENV, "5432"),
        "username": os.getenv(DATABASE_USER_ENV, ""),
        "password": os.getenv(DATABASE_PASSWORD_ENV, ""),
        "database": os.getenv(DATABASE_NAME_ENV, ""),
    }
    configured = any(
        os.getenv(name)
        for name in (
            DATABASE_HOST_ENV,
            DATABASE_PORT_ENV,
            DATABASE_USER_ENV,
            DATABASE_PASSWORD_ENV,
            DATABASE_NAME_ENV,
        )
    )
    if not configured:
        raise DatabaseConfigurationError(
            f"Set {DATABASE_URL_ENV} or all PostgreSQL connection settings."
        )
    try:
        port = int(components["port"])
    except ValueError as exc:
        raise DatabaseConfigurationError(
            f"{DATABASE_PORT_ENV} must be a valid port number."
        ) from exc
    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError(f"{DATABASE_PORT_ENV} must be between 1 and 65535.")
    if not all(components[key] for key in ("host", "username", "password", "database")):
        raise DatabaseConfigurationError(
            "All PostgreSQL connection settings must be provided together."
        )
    return _validate_database_url(
        URL.create(
            "postgresql+asyncpg",
            username=components["username"],
            password=components["password"],
            host=components["host"],
            port=port,
            database=components["database"],
        )
    )


def database_is_configured() -> bool:
    return bool(os.getenv(DATABASE_URL_ENV)) or any(
        os.getenv(name)
        for name in (
            DATABASE_HOST_ENV,
            DATABASE_PORT_ENV,
            DATABASE_USER_ENV,
            DATABASE_PASSWORD_ENV,
            DATABASE_NAME_ENV,
        )
    )


def _validate_database_url(url: URL) -> URL:
    if url.drivername != "postgresql+asyncpg" or not url.host or not url.database:
        raise DatabaseConfigurationError(
            f"{DATABASE_URL_ENV} must use postgresql+asyncpg with a host and database."
        )
    return url


def create_database_engine(url: URL | str | None = None) -> AsyncEngine:
    if url is None:
        resolved_url = database_url_from_env()
    else:
        try:
            resolved_url = _validate_database_url(make_url(url))
        except (ArgumentError, ValueError) as exc:
            raise DatabaseConfigurationError(
                f"{DATABASE_URL_ENV} must be a valid PostgreSQL connection URL."
            ) from exc
    return create_async_engine(
        resolved_url,
        pool_pre_ping=True,
        echo=False,
        hide_parameters=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        async with session.begin():
            yield session
