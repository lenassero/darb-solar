"""Plotly figures for the yearly plant-power dashboard view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from darb_solar.power.aggregates import aggregate_monthly_energy_kwh
from darb_solar.power.columns import COLLECTED_AT, SAVINGS_MAD
from darb_solar.power.constants import CURRENCY_LABEL, KWH_SERIES, SELF_CONSUMED_COLOR
from darb_solar.power.metrics import with_savings_mad
from darb_solar.viz.charts import build_stacked_energy_chart


def build_yearly_energy_chart(df: pd.DataFrame) -> go.Figure:
    """Build a stacked bar chart of monthly energy totals for one year.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_year_data`` for a single year.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked monthly bars with unified hover, text labels showing
        percentages, and default zoom/pan toolbar.
    """
    monthly_df = aggregate_monthly_energy_kwh(df)
    fig = build_stacked_energy_chart(
        monthly_df,
        KWH_SERIES,
        xaxis_title="Mois",
        yaxis_title="kWh",
    )

    # Add text labels for percentages
    if not monthly_df.empty:
        for trace_idx, (column, _, _) in enumerate(KWH_SERIES):
            values = monthly_df[column].values
            totals = monthly_df[[col for col, _, _ in KWH_SERIES]].sum(axis=1).values
            percentages = [
                f"{(value / total * 100):.0f}%" if total > 0 else "0%"
                for value, total in zip(values, totals)
            ]
            fig.data[trace_idx].text = percentages
            fig.data[trace_idx].textposition = "auto"
            fig.data[trace_idx].textfont = {
                "size": 16,
            }

    return fig


def build_yearly_savings_chart(df: pd.DataFrame) -> go.Figure:
    """Build a bar chart of monthly savings for one year.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_year_data`` for a single year.

    Returns
    -------
    plotly.graph_objects.Figure
        Monthly savings bar chart with unified hover and default
        zoom/pan toolbar.
    """
    savings_df = with_savings_mad(aggregate_monthly_energy_kwh(df))

    fig = go.Figure()
    if not savings_df.empty:
        fig.add_trace(
            go.Bar(
                x=savings_df[COLLECTED_AT],
                y=savings_df[SAVINGS_MAD],
                name="Économies réalisées",
                marker_color=SELF_CONSUMED_COLOR,
                hovertemplate=(f"%{{y:.1f}} {CURRENCY_LABEL}<extra></extra>"),
            )
        )

    fig.update_layout(
        xaxis_title="Mois",
        yaxis_title=CURRENCY_LABEL,
        hovermode="x unified",
        legend={"traceorder": "normal"},
        legend_title_text="",
    )
    return fig
