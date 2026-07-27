"""Shared Plotly figure builders."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from darb_solar.viz.style import (
    DONUT_HEIGHT,
    DONUT_HOLE,
    DONUT_TEXT_SIZE,
    donut_center_layout,
)


def build_energy_donut_chart(
    totals: list[tuple[str, float, str]],
    center_total_kwh: float,
) -> go.Figure:
    """Build a donut chart from pre-computed energy totals.

    Parameters
    ----------
    totals : list[tuple[str, float, str]]
        ``(label, kwh, color_hex)`` per energy flow.
    center_total_kwh : float
        Total consumption kWh shown at the center of the donut.

    Returns
    -------
    plotly.graph_objects.Figure
        Donut chart with sector labels and percentage shares in kWh.
    """
    slices = [(label, kwh, color) for label, kwh, color in totals if kwh > 0]

    fig = go.Figure()
    center_images, center_annotations = donut_center_layout(center_total_kwh)
    if not slices:
        fig.update_layout(
            height=DONUT_HEIGHT,
            margin=dict(t=15, b=60, l=15, r=15),
            images=center_images,
            annotations=center_annotations,
        )
        return fig

    labels, values, colors = zip(*slices, strict=True)
    pull = False
    fig.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            hole=DONUT_HOLE,
            pull=pull,
            sort=False,
            direction="counterclockwise",
            legendrank=list(range(len(labels))),
            marker={"colors": list(colors)},
            textinfo="percent",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont={"size": DONUT_TEXT_SIZE},
            hovertemplate=("%{label}<br>%{value:.1f} kWh<br>%{percent}<extra></extra>"),
        )
    )
    fig.update_layout(
        height=DONUT_HEIGHT,
        showlegend=True,
        legend={"traceorder": "normal"},
        margin=dict(t=10, b=60, l=10, r=10),
        images=center_images,
        annotations=center_annotations,
    )
    return fig


def build_stacked_energy_chart(
    chart_df: pd.DataFrame,
    series: tuple[tuple[str, str, str], ...],
    *,
    xaxis_title: str,
    yaxis_title: str,
    x_column: str = "collected_at",
) -> go.Figure:
    """Build a stacked bar chart for one or more energy series.

    Parameters
    ----------
    chart_df : pandas.DataFrame
        Data to plot, with columns referenced by ``series``.
    series : tuple[tuple[str, str, str], ...]
        ``(column, label, color)`` per trace.
    xaxis_title : str
        X-axis label.
    yaxis_title : str
        Y-axis label.
    x_column : str, optional
        Column used for the x-axis.

    Returns
    -------
    plotly.graph_objects.Figure
        Stacked bars with unified hover and default zoom/pan toolbar.
    """
    fig = go.Figure()
    if chart_df.empty:
        fig.update_layout(
            barmode="stack",
            xaxis_title=xaxis_title,
            yaxis_title=yaxis_title,
            hovermode="x unified",
        )
        return fig

    for index, (column, label, color) in enumerate(series):
        fig.add_trace(
            go.Bar(
                x=chart_df[x_column],
                y=chart_df[column],
                name=label,
                legendrank=index,
                marker_color=color,
                hovertemplate=f"%{{y:.2f}} {yaxis_title}<extra></extra>",
            )
        )

    fig.update_layout(
        barmode="stack",
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        hovermode="x unified",
        legend={"traceorder": "normal"},
        legend_title_text="",
    )
    return fig
