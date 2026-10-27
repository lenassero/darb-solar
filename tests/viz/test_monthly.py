"""Tests for ``darb_solar.viz.monthly``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")

from darb_solar.power.constants import KWH_SERIES  # noqa: E402
from darb_solar.viz.monthly import (  # noqa: E402
    build_hourly_mean_energy_chart,
    build_monthly_energy_chart,
)

ReadingsDfFactory = Callable[..., Any]
READINGS_PER_DAY = 24 * 12


def test_monthly_chart_has_one_bar_per_day(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Readings over two days yield two daily bars per series."""
    df = readings_df(
        [2.0] * 2 * READINGS_PER_DAY,
        [0.5] * 2 * READINGS_PER_DAY,
        [3.0] * 2 * READINGS_PER_DAY,
        start=datetime(2026, 6, 1, tzinfo=casablanca_tz),
    )

    fig = build_monthly_energy_chart(df)

    assert [trace.name for trace in fig.data] == [label for _, label, _ in KWH_SERIES]
    assert len(fig.data[0].x) == 2
    assert list(fig.data[0].y) == pytest.approx([36.0, 36.0])
    assert fig.layout.xaxis.title.text == "Jour"
    assert fig.layout.yaxis.title.text == "kWh"


def test_monthly_chart_with_empty_data_has_no_traces() -> None:
    """Empty input yields an empty stacked layout."""
    fig = build_monthly_energy_chart(pd.DataFrame())

    assert len(fig.data) == 0
    assert fig.layout.barmode == "stack"


def test_hourly_mean_chart_plots_hours_of_day(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> None:
    """Each trace has 24 hourly means and the x-axis shows ``HHh`` labels."""
    df = readings_df(
        [2.0] * READINGS_PER_DAY + [4.0] * READINGS_PER_DAY,
        [0.0] * 2 * READINGS_PER_DAY,
        [5.0] * 2 * READINGS_PER_DAY,
        start=datetime(2026, 6, 1, tzinfo=casablanca_tz),
    )

    fig = build_hourly_mean_energy_chart(df)

    assert list(fig.data[0].x) == list(range(24))
    assert list(fig.data[0].y) == pytest.approx([3.0] * 24)
    assert fig.layout.xaxis.title.text == "Heure"
    assert fig.layout.xaxis.tickmode == "array"
    assert list(fig.layout.xaxis.tickvals) == list(range(24))
    assert list(fig.layout.xaxis.ticktext) == [f"{hour:02d}h" for hour in range(24)]


def test_hourly_mean_chart_with_empty_data_keeps_hour_axis() -> None:
    """Empty input yields no traces but still configures the hour ticks."""
    fig = build_hourly_mean_energy_chart(pd.DataFrame())

    assert len(fig.data) == 0
    assert fig.layout.xaxis.ticktext[0] == "00h"
    assert fig.layout.xaxis.ticktext[-1] == "23h"
