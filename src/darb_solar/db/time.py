"""Timestamp helpers for database writes."""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
