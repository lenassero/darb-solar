"""Tests for ``darb_solar.viz.daily``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")

from darb_solar.power.constants import KW_SERIES, KWH_SERIES  # noqa: E402
from darb_solar.viz.daily import build_daily_energy_chart  # noqa: E402

ReadingsDfFactory = Callable[..., Any]


@pytest.fixture
def two_hours(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> Any:
    """Return two hours of constant five-minute readings.

    Parameters
    ----------
    readings_df : collections.abc.Callable
        The ``readings_df`` fixture.
    casablanca_tz : zoneinfo.ZoneInfo
        Plant-local timezone.

    Returns
    -------
    pandas.DataFrame
        24 readings: 2 kW production, 0.5 kW export, 3 kW consumption.
    """
    return readings_df(
        [2.0] * 24,
        [0.5] * 24,
        [3.0] * 24,
        start=datetime(2026, 6, 1, 10, tzinfo=casablanca_tz),
    )


def test_default_mode_plots_hourly_energy(two_hours: Any) -> None:
    """Without detail, readings are summed to hourly kWh bars."""
    fig = build_daily_energy_chart(two_hours)

    assert [trace.name for trace in fig.data] == [label for _, label, _ in KWH_SERIES]
    assert len(fig.data[0].x) == 2
    assert list(fig.data[0].y) == pytest.approx([1.5, 1.5])
    assert list(fig.data[1].y) == pytest.approx([0.5, 0.5])
    assert list(fig.data[2].y) == pytest.approx([1.0, 1.0])
    assert fig.layout.yaxis.title.text == "kWh"
    assert fig.layout.xaxis.title.text == "Heure"
    assert fig.layout.xaxis.tickformat == "%Hh"


def test_detail_mode_plots_five_minute_power(two_hours: Any) -> None:
    """With detail, each five-minute reading is plotted in kW."""
    fig = build_daily_energy_chart(two_hours, detail=True)

    assert [trace.name for trace in fig.data] == [label for _, label, _ in KW_SERIES]
    assert len(fig.data[0].x) == 24
    assert list(fig.data[0].y) == pytest.approx([1.5] * 24)
    assert list(fig.data[2].y) == pytest.approx([1.0] * 24)
    assert fig.layout.yaxis.title.text == "kW"
    assert fig.layout.xaxis.tickformat is None


@pytest.mark.parametrize(
    ("detail", "expected_unit"),
    [(False, "kWh"), (True, "kW")],
)
def test_empty_data_keeps_axis_titles(detail: bool, expected_unit: str) -> None:
    """Empty input produces no traces but the unit-specific axis title."""
    fig = build_daily_energy_chart(pd.DataFrame(), detail=detail)

    assert len(fig.data) == 0
    assert fig.layout.yaxis.title.text == expected_unit
    assert fig.layout.xaxis.title.text == "Heure"


def test_empty_data_in_default_mode_formats_ticks_as_hours() -> None:
    """The hour tick format is applied even when there is no data."""
    fig = build_daily_energy_chart(pd.DataFrame())

    assert fig.layout.xaxis.tickformat == "%Hh"
