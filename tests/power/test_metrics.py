"""Tests for ``darb_solar.power.metrics``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")

from darb_solar.power import metrics  # noqa: E402
from darb_solar.power.constants import (  # noqa: E402
    ELECTRICITY_PRICE_MAD_PER_KWH,
    GRID_EXPORT_COLOR,
    GRID_EXPORT_LABEL,
    GRID_IMPORT_COLOR,
    GRID_IMPORT_LABEL,
    SELF_CONSUMED_COLOR,
    SELF_CONSUMED_LABEL,
)

ReadingsDfFactory = Callable[..., Any]


def test_total_consumption_sums_interval_energy(
    readings_df: ReadingsDfFactory,
) -> None:
    """Total consumption is the sum of the per-interval kWh."""
    df = readings_df([0.0] * 3, [0.0] * 3, [12.0, 24.0, 0.0])

    assert metrics.total_consumption_kwh(df) == pytest.approx(3.0)


def test_total_consumption_of_empty_frame_is_zero() -> None:
    """An empty frame has zero consumption."""
    assert metrics.total_consumption_kwh(pd.DataFrame()) == 0.0


def test_summarize_energy_returns_labeled_totals_with_colors(
    readings_df: ReadingsDfFactory,
) -> None:
    """Each flow is reported with its label, summed kWh and chart color."""
    df = readings_df([12.0] * 12, [2.0] * 12, [20.0] * 12)

    summary = metrics.summarize_energy_kwh(df)

    assert summary == [
        (SELF_CONSUMED_LABEL, pytest.approx(10.0), SELF_CONSUMED_COLOR),
        (GRID_EXPORT_LABEL, pytest.approx(2.0), GRID_EXPORT_COLOR),
        (GRID_IMPORT_LABEL, pytest.approx(8.0), GRID_IMPORT_COLOR),
    ]


def test_summarize_energy_of_empty_frame_is_all_zero() -> None:
    """An empty frame yields zero totals for every flow."""
    summary = metrics.summarize_energy_kwh(pd.DataFrame())

    assert [kwh for _label, kwh, _color in summary] == [0.0, 0.0, 0.0]
    assert [label for label, _kwh, _color in summary] == [
        SELF_CONSUMED_LABEL,
        GRID_EXPORT_LABEL,
        GRID_IMPORT_LABEL,
    ]


def test_mean_daily_consumption_divides_by_distinct_dates(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Total consumption is divided by the number of days with readings."""
    start = datetime(2026, 6, 1, 23, tzinfo=casablanca_tz)
    df = readings_df([0.0] * 24, [0.0] * 24, [6.0] * 24, start=start)

    assert metrics.mean_daily_consumption_kwh(df) == pytest.approx(12.0 / 2)


def test_mean_daily_consumption_of_empty_frame_is_zero() -> None:
    """An empty frame has zero mean daily consumption."""
    assert metrics.mean_daily_consumption_kwh(pd.DataFrame()) == 0.0


def test_with_savings_mad_uses_default_price(
    readings_df: ReadingsDfFactory,
) -> None:
    """Savings default to the self-consumed energy times the default price."""
    df = readings_df([12.0], [0.0], [12.0])

    result = metrics.with_savings_mad(df)

    assert result["savings_mad"].iloc[0] == pytest.approx(
        1.0 * ELECTRICITY_PRICE_MAD_PER_KWH
    )
    assert "savings_mad" not in df.columns


def test_with_savings_mad_uses_custom_price(readings_df: ReadingsDfFactory) -> None:
    """A custom price scales the savings column."""
    df = readings_df([12.0], [0.0], [12.0])

    assert metrics.with_savings_mad(df, price=1.5)["savings_mad"].iloc[0] == (
        pytest.approx(1.5)
    )


def test_total_savings_prices_self_consumed_energy(
    readings_df: ReadingsDfFactory,
) -> None:
    """Total savings are the self-consumed kWh times the price."""
    df = readings_df([12.0] * 12, [2.0] * 12, [20.0] * 12)

    assert metrics.total_savings_mad(df) == pytest.approx(
        10.0 * ELECTRICITY_PRICE_MAD_PER_KWH
    )
    assert metrics.total_savings_mad(df, price=2.0) == pytest.approx(20.0)


def test_total_savings_of_empty_frame_is_zero() -> None:
    """An empty frame yields zero savings."""
    assert metrics.total_savings_mad(pd.DataFrame()) == 0.0
