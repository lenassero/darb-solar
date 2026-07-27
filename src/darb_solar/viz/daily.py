"""Plotly figures for the daily plant-power dashboard view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from darb_solar.power.aggregates import aggregate_hourly_energy_kwh
from darb_solar.power.constants import KW_SERIES, KWH_SERIES
from darb_solar.viz.charts import build_stacked_energy_chart


def build_daily_energy_chart(df: pd.DataFrame, *, detail: bool = False) -> go.Figure:
    """Build a stacked bar chart of daily energy or power versus time of day.

    By default, five-minute power readings are aggregated into hourly
    energy bars in kWh. When ``detail`` is true, the raw five-minute
    power series are shown in kW.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_day_data`` for a single day.
    detail : bool, optional
        When true, plot five-minute power in kW instead of hourly energy
        in kWh.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked bars with unified hover and default zoom/pan toolbar.
    """
    yaxis_title = "kW" if detail else "kWh"
    if detail or df.empty:
        chart_df = df
        series = KW_SERIES if detail else KWH_SERIES
    else:
        chart_df = aggregate_hourly_energy_kwh(df)
        series = KWH_SERIES

    fig = build_stacked_energy_chart(
        chart_df,
        series,
        xaxis_title="Heure",
        yaxis_title=yaxis_title,
    )
    if not detail:
        fig.update_xaxes(tickformat="%Hh")
    return fig
