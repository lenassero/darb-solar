"""Timezone-aware datetime and epoch-millisecond helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Plant local time (Morocco, UTC+1 year-round).
DEFAULT_TIMEZONE = ZoneInfo("Africa/Casablanca")


def datetime_to_epoch_ms(when: datetime) -> int:
    """Convert a timezone-aware datetime to epoch milliseconds.

    Parameters
    ----------
    when : datetime
        Timezone-aware datetime.

    Returns
    -------
    int
        Milliseconds since epoch.
    """
    if when.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return int(when.timestamp() * 1000)


def day_bounds_epoch_ms(
    day: datetime,
    *,
    tz: ZoneInfo = DEFAULT_TIMEZONE,
) -> tuple[int, int]:
    """Return ``(start_ms, end_ms)`` for a calendar day in ``tz``.

    Parameters
    ----------
    day : datetime
        Any datetime on the target day. Its timezone is used when set;
        otherwise ``tz`` is applied.
    """
    local_day = day if day.tzinfo is not None else day.replace(tzinfo=tz)
    start = local_day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return datetime_to_epoch_ms(start), datetime_to_epoch_ms(end)


def datetime_from_epoch_ms(
    epoch_ms: int | None,
    *,
    tz: ZoneInfo = DEFAULT_TIMEZONE,
) -> datetime | None:
    """Convert epoch milliseconds to a timezone-aware datetime.

    Parameters
    ----------
    epoch_ms : int or None
        Milliseconds since epoch, for example FusionSolar ``collectTime``.
    tz : ZoneInfo, optional
        Target timezone. Defaults to ``DEFAULT_TIMEZONE`` (Casablanca, UTC+1).

    Returns
    -------
    datetime or None
        Timezone-aware datetime, or ``None`` when ``epoch_ms`` is missing.
    """
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=tz)
