"""Tests for ``darb_solar.power.aggregates``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")

from darb_solar.power import aggregates  # noqa: E402

ReadingsDfFactory = Callable[..., Any]

ENERGY_COLUMNS = ["self_consumed_kwh", "grid_export_kwh", "grid_import_kwh"]
READINGS_PER_HOUR = 12


def _constant_readings(
    readings_df: ReadingsDfFactory,
    count: int,
    start: datetime,
) -> Any:
    """Build `count` readings of 2 kW production, 0.5 kW export, 3 kW load.

    Each reading therefore carries 1.5 kW self-consumed and 1 kW imported.

    Parameters
    ----------
    readings_df : collections.abc.Callable
        The ``readings_df`` fixture.
    count : int
        Number of five-minute readings.
    start : datetime.datetime
        Timestamp of the first reading.

    Returns
    -------
    pandas.DataFrame
        Readings with derived columns.
    """
    return readings_df([2.0] * count, [0.5] * count, [3.0] * count, start=start)


@pytest.mark.parametrize(
    "aggregate",
    [
        aggregates.aggregate_hourly_energy_kwh,
        aggregates.aggregate_daily_energy_kwh,
        aggregates.aggregate_monthly_energy_kwh,
    ],
)
def test_empty_input_returns_empty_energy_schema(
    aggregate: Callable[[Any], Any],
) -> None:
    """Empty input yields an empty frame with the energy schema."""
    result = aggregate(pd.DataFrame())

    assert result.empty
    assert list(result.columns) == ["collected_at", *ENERGY_COLUMNS]


def test_hourly_mean_empty_input_returns_empty_schema() -> None:
    """Empty input yields an empty frame with the hour schema."""
    result = aggregates.aggregate_hourly_mean_energy_kwh(pd.DataFrame())

    assert result.empty
    assert list(result.columns) == ["hour", *ENERGY_COLUMNS]


def test_hourly_aggregate_sums_twelve_readings_per_hour(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Two hours of constant readings yield two hourly rows of equal totals."""
    start = datetime(2026, 6, 1, 10, tzinfo=casablanca_tz)
    df = _constant_readings(readings_df, 2 * READINGS_PER_HOUR, start)

    result = aggregates.aggregate_hourly_energy_kwh(df)

    assert result["collected_at"].tolist() == [
        pd.Timestamp(start),
        pd.Timestamp(start.replace(hour=11)),
    ]
    assert result["self_consumed_kwh"].tolist() == pytest.approx([1.5, 1.5])
    assert result["grid_export_kwh"].tolist() == pytest.approx([0.5, 0.5])
    assert result["grid_import_kwh"].tolist() == pytest.approx([1.0, 1.0])


def test_daily_aggregate_splits_at_local_midnight(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Readings straddling midnight are split into two daily rows."""
    start = datetime(2026, 6, 1, 22, tzinfo=casablanca_tz)
    df = _constant_readings(readings_df, 4 * READINGS_PER_HOUR, start)

    result = aggregates.aggregate_daily_energy_kwh(df)

    assert [ts.day for ts in result["collected_at"]] == [1, 2]
    assert result["self_consumed_kwh"].tolist() == pytest.approx([3.0, 3.0])
    assert result["grid_import_kwh"].tolist() == pytest.approx([2.0, 2.0])


def test_monthly_aggregate_splits_at_month_start(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Readings straddling a month boundary yield one row per month start."""
    start = datetime(2026, 5, 31, 23, tzinfo=casablanca_tz)
    df = _constant_readings(readings_df, 2 * READINGS_PER_HOUR, start)

    result = aggregates.aggregate_monthly_energy_kwh(df)

    assert [(ts.month, ts.day) for ts in result["collected_at"]] == [(5, 1), (6, 1)]
    assert result["self_consumed_kwh"].tolist() == pytest.approx([1.5, 1.5])


def test_hourly_mean_averages_hour_of_day_across_dates(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Each hour of day is averaged over the days present in the data."""
    per_day = 24 * READINGS_PER_HOUR
    df = readings_df(
        pv_production_kw=[2.0] * per_day + [4.0] * per_day,
        grid_export_kw=[0.0] * 2 * per_day,
        consumption_kw=[5.0] * 2 * per_day,
        start=datetime(2026, 6, 1, tzinfo=casablanca_tz),
    )

    result = aggregates.aggregate_hourly_mean_energy_kwh(df)

    assert result["hour"].tolist() == list(range(24))
    assert result["self_consumed_kwh"].tolist() == pytest.approx([3.0] * 24)
    assert result["grid_export_kwh"].tolist() == pytest.approx([0.0] * 24)
    assert result["grid_import_kwh"].tolist() == pytest.approx([2.0] * 24)
