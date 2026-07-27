"""Plotly figures for the monthly plant-power dashboard view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from darb_solar.power.aggregates import (
    aggregate_daily_energy_kwh,
    aggregate_hourly_mean_energy_kwh,
)
from darb_solar.power.constants import KWH_SERIES
from darb_solar.viz.charts import build_stacked_energy_chart


def build_monthly_energy_chart(df: pd.DataFrame) -> go.Figure:
    """Build a stacked bar chart of daily energy totals for one month.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_month_data`` for a single month.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked daily bars with unified hover and default zoom/pan toolbar.
    """
    return build_stacked_energy_chart(
        aggregate_daily_energy_kwh(df),
        KWH_SERIES,
        xaxis_title="Jour",
        yaxis_title="kWh",
    )


def build_hourly_mean_energy_chart(df: pd.DataFrame) -> go.Figure:
    """Build a stacked bar chart of mean energy kWh per hour-of-day.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval spanning
        multiple days.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked bars with unified hover and default zoom/pan toolbar.
    """
    fig = build_stacked_energy_chart(
        aggregate_hourly_mean_energy_kwh(df),
        KWH_SERIES,
        xaxis_title="Heure",
        yaxis_title="kWh",
        x_column="hour",
    )
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(24)),
        ticktext=[f"{hour:02d}h" for hour in range(24)],
    )
    return fig
