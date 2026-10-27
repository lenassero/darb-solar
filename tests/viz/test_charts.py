"""Tests for ``darb_solar.viz.charts``."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")

from darb_solar.power.constants import (  # noqa: E402
    GRID_EXPORT_COLOR,
    GRID_EXPORT_LABEL,
    GRID_IMPORT_COLOR,
    GRID_IMPORT_LABEL,
    KWH_SERIES,
    SELF_CONSUMED_COLOR,
    SELF_CONSUMED_LABEL,
)
from darb_solar.viz import charts  # noqa: E402
from darb_solar.viz.style import DONUT_HEIGHT, DONUT_HOLE  # noqa: E402

TOTALS = [
    (SELF_CONSUMED_LABEL, 10.0, SELF_CONSUMED_COLOR),
    (GRID_EXPORT_LABEL, 2.0, GRID_EXPORT_COLOR),
    (GRID_IMPORT_LABEL, 8.0, GRID_IMPORT_COLOR),
]


@pytest.fixture(autouse=True)
def _stub_donut_center(mocker: MockerFixture) -> None:
    """Replace the donut center layout so no icon file is read.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    """
    mocker.patch.object(
        charts,
        "donut_center_layout",
        side_effect=lambda total: (
            [{"source": "data:x"}],
            [{"text": f"{total:.1f}kWh"}],
        ),
    )


def test_donut_chart_has_one_pie_with_matching_slices() -> None:
    """Each non-empty flow becomes a slice with its label and color."""
    fig = charts.build_energy_donut_chart(TOTALS, center_total_kwh=20.0)

    assert len(fig.data) == 1
    pie = fig.data[0]
    assert list(pie.labels) == [label for label, _, _ in TOTALS]
    assert list(pie.values) == [10.0, 2.0, 8.0]
    assert list(pie.marker.colors) == [color for _, _, color in TOTALS]
    assert pie.hole == DONUT_HOLE
    assert pie.sort is False
    assert fig.layout.height == DONUT_HEIGHT
    assert fig.layout.showlegend is True


def test_donut_chart_drops_zero_slices() -> None:
    """Flows with no energy are omitted from the pie."""
    totals = [TOTALS[0], (GRID_EXPORT_LABEL, 0.0, GRID_EXPORT_COLOR), TOTALS[2]]

    fig = charts.build_energy_donut_chart(totals, center_total_kwh=18.0)

    assert list(fig.data[0].labels) == [SELF_CONSUMED_LABEL, GRID_IMPORT_LABEL]
    assert list(fig.data[0].values) == [10.0, 8.0]


def test_donut_chart_shows_center_total() -> None:
    """The center icon and total are attached to the layout."""
    fig = charts.build_energy_donut_chart(TOTALS, center_total_kwh=20.0)

    assert fig.layout.annotations[0].text == "20.0kWh"
    assert fig.layout.images[0].source == "data:x"


def test_donut_chart_without_energy_is_empty_but_keeps_center() -> None:
    """When every flow is zero, no trace is drawn but the center remains."""
    totals = [(label, 0.0, color) for label, _, color in TOTALS]

    fig = charts.build_energy_donut_chart(totals, center_total_kwh=0.0)

    assert len(fig.data) == 0
    assert fig.layout.height == DONUT_HEIGHT
    assert fig.layout.annotations[0].text == "0.0kWh"


def test_donut_chart_without_totals_is_empty() -> None:
    """An empty totals list yields an empty figure."""
    fig = charts.build_energy_donut_chart([], center_total_kwh=0.0)

    assert len(fig.data) == 0


def test_stacked_chart_has_one_bar_trace_per_series() -> None:
    """Each series becomes a stacked bar trace with its label and color."""
    chart_df = pd.DataFrame(
        {
            "collected_at": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "self_consumed_kwh": [1.0, 2.0],
            "grid_export_kwh": [0.5, 0.0],
            "grid_import_kwh": [3.0, 4.0],
        }
    )

    fig = charts.build_stacked_energy_chart(
        chart_df,
        KWH_SERIES,
        xaxis_title="Jour",
        yaxis_title="kWh",
    )

    assert [trace.name for trace in fig.data] == [
        SELF_CONSUMED_LABEL,
        GRID_EXPORT_LABEL,
        GRID_IMPORT_LABEL,
    ]
    assert [trace.marker.color for trace in fig.data] == [
        SELF_CONSUMED_COLOR,
        GRID_EXPORT_COLOR,
        GRID_IMPORT_COLOR,
    ]
    assert [trace.legendrank for trace in fig.data] == [0, 1, 2]
    assert list(fig.data[2].y) == [3.0, 4.0]
    assert fig.data[0].hovertemplate == "%{y:.2f} kWh<extra></extra>"
    assert fig.layout.barmode == "stack"
    assert fig.layout.xaxis.title.text == "Jour"
    assert fig.layout.yaxis.title.text == "kWh"
    assert fig.layout.hovermode == "x unified"


def test_stacked_chart_uses_custom_x_column() -> None:
    """`x_column` selects the column plotted on the x-axis."""
    chart_df = pd.DataFrame({"hour": [0, 1], "self_consumed_kwh": [1.0, 2.0]})

    fig = charts.build_stacked_energy_chart(
        chart_df,
        (("self_consumed_kwh", "Label", "#000000"),),
        xaxis_title="Heure",
        yaxis_title="kWh",
        x_column="hour",
    )

    assert list(fig.data[0].x) == [0, 1]


def test_stacked_chart_with_empty_data_only_sets_layout() -> None:
    """Empty data yields no traces but keeps the axis layout."""
    fig = charts.build_stacked_energy_chart(
        pd.DataFrame(),
        KWH_SERIES,
        xaxis_title="Jour",
        yaxis_title="kWh",
    )

    assert len(fig.data) == 0
    assert fig.layout.barmode == "stack"
    assert fig.layout.xaxis.title.text == "Jour"
    assert fig.layout.yaxis.title.text == "kWh"
    assert fig.layout.hovermode == "x unified"
