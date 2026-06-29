"""SQLite connection and schema initialization."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from darb_solar.db.schema import SCHEMA_SQL

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "fusionsolar.db"
DEFAULT_TIMEZONE_NAME = "Africa/Casablanca"


def resolve_db_path(
    db_path: Path | None = None,
    *,
    database_url: str | None = None,
) -> Path:
    """Resolve the SQLite database file path.

    Parameters
    ----------
    db_path : Path or None, optional
        Explicit database path. Takes precedence over ``database_url``.
    database_url : str or None, optional
        Database URL from ``DARB_SOLAR_DATABASE_URL`` when ``db_path`` is
        omitted.

    Returns
    -------
    Path
        Path to the SQLite database file.

    Raises
    ------
    ValueError
        If the URL scheme is not ``sqlite``.
    """
    if db_path is not None:
        return db_path.resolve()

    url = database_url if database_url is not None else os.environ.get(
        "DARB_SOLAR_DATABASE_URL"
    )
    if not url:
        return DEFAULT_DB_PATH.resolve()

    if not url.startswith("sqlite:///"):
        msg = (
            "Only sqlite:/// URLs are supported for now; "
            f"got {url!r}."
        )
        raise ValueError(msg)

    raw_path = url.removeprefix("sqlite:///")
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists.

    Parameters
    ----------
    db_path : Path or None, optional
        Path to the SQLite database file. Defaults to
        ``resolve_db_path()``.

    Returns
    -------
    sqlite3.Connection
        Connection with ``row_factory`` set to ``sqlite3.Row``.
    """
    resolved_path = resolve_db_path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not already exist.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    """
    connection.executescript(SCHEMA_SQL)
    connection.commit()
