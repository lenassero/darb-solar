"""Postgres connection helpers for SQLAlchemy sessions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DbSession = Session

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TIMEZONE_NAME = "Africa/Casablanca"
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://darb_solar:darb_solar@localhost:5432/darb_solar"
)

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}


def resolve_database_url(database_url: str | None = None) -> str:
    """Resolve the Postgres database URL.

    Parameters
    ----------
    database_url : str or None, optional
        Explicit database URL. When omitted, uses ``DARB_SOLAR_DATABASE_URL``
        from the environment, then ``DEFAULT_DATABASE_URL``.

    Returns
    -------
    str
        Postgres connection URL.
    """
    if database_url is not None:
        return normalize_database_url(database_url)

    return normalize_database_url(
        os.environ.get("DARB_SOLAR_DATABASE_URL", DEFAULT_DATABASE_URL)
    )


def normalize_database_url(database_url: str) -> str:
    """Normalize a Postgres URL for SQLAlchemy + psycopg3.

    Accepts hosted-Postgres URLs in ``postgresql://`` form and rewrites them to
    ``postgresql+psycopg://`` so callers do not need dialect-specific env vars.
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def redact_database_url(database_url: str) -> str:
    """Return a log-safe database URL with credentials removed."""
    parsed = urlsplit(database_url)
    if "@" not in parsed.netloc:
        return database_url

    _, host = parsed.netloc.rsplit("@", 1)
    redacted = parsed._replace(netloc=f"***:***@{host}")
    return urlunsplit(redacted)


def get_engine(database_url: str | None = None) -> Engine:
    """Return a cached SQLAlchemy engine for the resolved database URL.

    Parameters
    ----------
    database_url : str or None, optional
        Postgres connection URL. Defaults to ``resolve_database_url()``.

    Returns
    -------
    sqlalchemy.engine.Engine
        Engine connected via the psycopg3 dialect.
    """
    url = resolve_database_url(database_url)
    if url not in _engines:
        _engines[url] = create_engine(url)
        _session_factories[url] = sessionmaker(bind=_engines[url])
    return _engines[url]


def _get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    url = resolve_database_url(database_url)
    get_engine(database_url)
    return _session_factories[url]


@contextmanager
def get_session(database_url: str | None = None) -> Iterator[Session]:
    """Yield a SQLAlchemy session with automatic commit or rollback.

    Parameters
    ----------
    database_url : str or None, optional
        Postgres connection URL. Defaults to ``resolve_database_url()``.

    Yields
    ------
    sqlalchemy.orm.Session
        Open database session.
    """
    with _get_session_factory(database_url).begin() as session:
        yield session
