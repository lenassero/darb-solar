"""Tests for ``darb_solar.time``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from darb_solar.time import (
    datetime_from_epoch_ms,
    datetime_to_epoch_ms,
    day_bounds_epoch_ms,
)

HOUR_MS = 60 * 60 * 1000


def test_datetime_to_epoch_ms_rejects_naive_datetime() -> None:
    """A naive datetime raises instead of assuming a timezone."""
    with pytest.raises(ValueError, match="timezone-aware"):
        datetime_to_epoch_ms(datetime(2026, 6, 1))


def test_datetime_to_epoch_ms_converts_aware_datetime() -> None:
    """An aware datetime converts to milliseconds since the epoch."""
    when = datetime(2026, 1, 1, 0, 0, 0, 500_000, tzinfo=timezone.utc)

    assert datetime_to_epoch_ms(when) == 1_767_225_600_500


@pytest.mark.parametrize(
    ("day", "expected_hours"),
    [
        pytest.param(datetime(2026, 6, 1, 12), 24, id="normal-day"),
        pytest.param(datetime(2026, 2, 15, 12), 25, id="clock-back-25h-day"),
        pytest.param(datetime(2026, 3, 22, 12), 23, id="clock-forward-23h-day"),
    ],
)
def test_day_bounds_epoch_ms_spans_local_day(
    day: datetime,
    expected_hours: int,
    casablanca_tz: ZoneInfo,
) -> None:
    """Bounds are local midnights, so a clock change makes the day 23h or 25h."""
    start_ms, end_ms = day_bounds_epoch_ms(day, tz=casablanca_tz)

    local_midnight = day.replace(hour=0, tzinfo=casablanca_tz)
    assert start_ms == datetime_to_epoch_ms(local_midnight)
    assert end_ms - start_ms == expected_hours * HOUR_MS


def test_day_bounds_epoch_ms_uses_default_timezone_for_naive_day(
    casablanca_tz: ZoneInfo,
) -> None:
    """A naive day is interpreted in the default Casablanca timezone."""
    day = datetime(2026, 6, 1, 18, 30)

    assert day_bounds_epoch_ms(day) == day_bounds_epoch_ms(day, tz=casablanca_tz)


def test_day_bounds_epoch_ms_keeps_timezone_of_aware_day(
    casablanca_tz: ZoneInfo,
) -> None:
    """An aware day keeps its own timezone instead of `tz`."""
    day = datetime(2026, 6, 1, 23, 30, tzinfo=timezone.utc)

    start_ms, end_ms = day_bounds_epoch_ms(day, tz=casablanca_tz)

    utc_midnight = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert start_ms == datetime_to_epoch_ms(utc_midnight)
    assert end_ms == datetime_to_epoch_ms(utc_midnight + timedelta(days=1))


def test_datetime_from_epoch_ms_passes_none_through() -> None:
    """A missing timestamp returns ``None``."""
    assert datetime_from_epoch_ms(None) is None


def test_datetime_from_epoch_ms_returns_plant_local_datetime(
    casablanca_tz: ZoneInfo,
) -> None:
    """Milliseconds convert to an aware datetime in the default timezone."""
    expected = datetime(2026, 6, 1, 12, 5, tzinfo=casablanca_tz)

    result = datetime_from_epoch_ms(datetime_to_epoch_ms(expected))

    assert result == expected
    assert result.tzinfo == casablanca_tz
    assert result.hour == 12


def test_datetime_from_epoch_ms_honours_custom_timezone() -> None:
    """The `tz` argument controls the timezone of the returned datetime."""
    result = datetime_from_epoch_ms(1_767_225_600_000, tz=ZoneInfo("UTC"))

    assert result == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert result.tzinfo == ZoneInfo("UTC")
