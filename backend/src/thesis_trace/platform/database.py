from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool


class DatabaseUrlProvider(Protocol):
    """Resolve a database URL for one connection attempt without retaining it."""

    def __call__(self) -> str: ...


class PostgresUnavailable(RuntimeError):
    """Stable non-secret error for unavailable PostgreSQL capability."""


def _psycopg() -> Any:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("postgres_driver_unavailable") from exc
    return psycopg


def create_database_engine(database_url_provider: DatabaseUrlProvider) -> Engine:
    """Create a SQLAlchemy 2 engine without retaining the secret-bearing URL."""
    return create_engine(
        "postgresql+psycopg://",
        creator=lambda: _psycopg().connect(database_url_provider()),
        poolclass=NullPool,
    )


@contextmanager
def database_connection(
    engine: Engine, *, isolation_level: str | None = None,
) -> Iterator[Connection]:
    try:
        with engine.connect() as raw_connection:
            connection = (
                raw_connection.execution_options(isolation_level=isolation_level)
                if isolation_level is not None else raw_connection
            )
            with connection.begin():
                yield connection
    except (PermissionError, ValueError, LookupError):
        raise
    except Exception as exc:
        # Keep credentials and driver diagnostics out of API-visible errors.
        raise PostgresUnavailable("postgres_unavailable") from exc
