"""Tests for ``darb_solar.viz.yearly``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")

from darb_solar.power.constants import (  # noqa: E402
    CURRENCY_LABEL,
    KWH_SERIES,
    SELF_CONSUMED_COLOR,
)
from darb_solar.viz.yearly import (  # noqa: E402
    build_yearly_energy_chart,
    build_yearly_savings_chart,
)

ReadingsDfFactory = Callable[..., Any]
READINGS_PER_HOUR = 12


@pytest.fixture
def may_and_idle_june(
    readings_df: ReadingsDfFactory,
    casablanca_tz: ZoneInfo,
) -> Any:
    """Return one active hour in May followed by one idle hour in June.

    Parameters
    ----------
    readings_df : collections.abc.Callable
        The ``readings_df`` fixture.
    casablanca_tz : zoneinfo.ZoneInfo
        Plant-local timezone.

    Returns
    -------
    pandas.DataFrame
        May has 1.5 kWh self-consumed, 0.5 kWh exported and 1 kWh
        imported; June has no energy at all.
    """
    may = readings_df(
        [2.0] * READINGS_PER_HOUR,
        [0.5] * READINGS_PER_HOUR,
        [3.0] * READINGS_PER_HOUR,
        start=datetime(2026, 5, 31, 23, tzinfo=casablanca_tz),
    )
    june = readings_df(
        [0.0] * READINGS_PER_HOUR,
        [0.0] * READINGS_PER_HOUR,
        [0.0] * READINGS_PER_HOUR,
        start=datetime(2026, 6, 1, tzinfo=casablanca_tz),
    )
    return pd.concat([may, june], ignore_index=True)


def test_yearly_energy_chart_has_monthly_bars(may_and_idle_june: Any) -> None:
    """One stacked bar per month and series, with axis titles."""
    fig = build_yearly_energy_chart(may_and_idle_june)

    assert [trace.name for trace in fig.data] == [label for _, label, _ in KWH_SERIES]
    assert len(fig.data[0].x) == 2
    assert list(fig.data[0].y) == pytest.approx([1.5, 0.0])
    assert fig.layout.xaxis.title.text == "Mois"
    assert fig.layout.yaxis.title.text == "kWh"


def test_yearly_energy_chart_labels_bars_with_percentages(
    may_and_idle_june: Any,
) -> None:
    """Labels show each flow's share of the month, ``0%`` for an idle month."""
    fig = build_yearly_energy_chart(may_and_idle_june)

    assert list(fig.data[0].text) == ["50%", "0%"]
    assert list(fig.data[1].text) == ["17%", "0%"]
    assert list(fig.data[2].text) == ["33%", "0%"]
    assert all(trace.textposition == "auto" for trace in fig.data)
    assert all(trace.textfont.size == 16 for trace in fig.data)


def test_yearly_energy_chart_with_empty_data_has_no_traces() -> None:
    """Empty input yields an empty stacked layout without labels."""
    fig = build_yearly_energy_chart(pd.DataFrame())

    assert len(fig.data) == 0
    assert fig.layout.xaxis.title.text == "Mois"


def test_yearly_savings_chart_prices_self_consumed_energy(
    may_and_idle_june: Any,
) -> None:
    """Monthly savings bars equal self-consumed kWh times the default price."""
    fig = build_yearly_savings_chart(may_and_idle_june)

    assert len(fig.data) == 1
    bar = fig.data[0]
    assert bar.name == "Économies réalisées"
    assert bar.marker.color == SELF_CONSUMED_COLOR
    assert list(bar.y) == pytest.approx([1.5, 0.0])
    assert bar.hovertemplate == f"%{{y:.1f}} {CURRENCY_LABEL}<extra></extra>"
    assert fig.layout.xaxis.title.text == "Mois"
    assert fig.layout.yaxis.title.text == CURRENCY_LABEL
    assert fig.layout.hovermode == "x unified"


def test_yearly_savings_chart_with_empty_data_has_no_bars() -> None:
    """Empty input yields a figure without traces but with axis titles."""
    fig = build_yearly_savings_chart(pd.DataFrame())

    assert len(fig.data) == 0
    assert fig.layout.yaxis.title.text == CURRENCY_LABEL
