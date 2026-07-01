"""Timestamp helpers for database writes."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC timestamp as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)
