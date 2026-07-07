"""Daily plant-power chart data and Plotly figure builders."""

from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from darb_solar.db import DbSession
from darb_solar.db.models import PlantPowerReading
from darb_solar.db.reads import list_plant_power_readings

_FIVE_MINUTES_MS = 5 * 60 * 1000
_ONE_HOUR_MS = 60 * 60 * 1000
_INTERVAL_HOURS = 5 / 60

_SERIES = (
    ("self_consumed_kw", "Solaire consommé", "#7B2CBF"),
    ("grid_export_kw", "Solaire ré-injecté", "#2E86AB"),
    ("grid_import_kw", "Électricité achetée", "#C1121F"),
)

_SERIES_BG_COLORS = {
    "self_consumed_kw": "#EDE0F5",
    "grid_export_kw": "#D8ECF5",
    "grid_import_kw": "#F9DEDC",
}

_DONUT_HEIGHT = 360
_DONUT_HOLE = 0.4
_DONUT_PULL = 0.08
_DONUT_TEXT_SIZE = 22
_SELF_CONSUMED_LABEL = _SERIES[0][1]
_HOME_CONSUMPTION_ICON = (
    Path(__file__).resolve().parents[3] / "images" / "home_consumption.png"
)
_CENTER_ICON_Y = 0.58
_CENTER_TEXT_Y = 0.42
_CENTER_ICON_SIZE = 0.12


def _home_consumption_icon_source() -> str:
    encoded = base64.b64encode(_HOME_CONSUMPTION_ICON.read_bytes()).decode()
    return f"data:image/png;base64,{encoded}"


def _donut_center_layout(total_kwh: float) -> tuple[list[dict], list[dict]]:
    images = [
        {
            "source": _home_consumption_icon_source(),
            "xref": "paper",
            "yref": "paper",
            "x": 0.5,
            "y": _CENTER_ICON_Y,
            "sizex": _CENTER_ICON_SIZE,
            "sizey": _CENTER_ICON_SIZE,
            "xanchor": "center",
            "yanchor": "middle",
            "layer": "above",
        }
    ]
    annotations = [
        {
            "text": f"{total_kwh:.1f}kWh",
            "x": 0.5,
            "y": _CENTER_TEXT_Y,
            "xref": "paper",
            "yref": "paper",
            "xanchor": "center",
            "yanchor": "middle",
            "showarrow": False,
            "font": {"size": 20},
        }
    ]
    return images, annotations


def _total_consumption_kwh(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return df["consumption_kw"].sum() * _INTERVAL_HOURS


def _plant_reading_rows(readings: list[PlantPowerReading]) -> list[dict[str, object]]:
    return [
        {
            "plant_code": reading.plant_code,
            "collected_at": reading.collected_at,
            "pv_production_kw": reading.pv_production_kw,
            "grid_export_kw": reading.grid_export_kw,
            "consumption_kw": reading.consumption_kw,
            "synced_at": reading.synced_at,
        }
        for reading in readings
    ]


def load_day_data(
    session: DbSession,
    plant_code: str,
    day: date,
    tz: ZoneInfo,
) -> pd.DataFrame:
    """Load plant power readings for one calendar day with derived kW series.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    day : date
        Calendar day in the plant timezone.
    tz : ZoneInfo
        Plant-local timezone used for day boundaries and the x-axis.

    Returns
    -------
    pandas.DataFrame
        Rows for ``[day_start, day_end)`` with raw plant readings plus
        ``self_consumed_kw``, ``grid_export_kw``, and ``grid_import_kw``.
    """
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    readings = list_plant_power_readings(
        session,
        plant_code=plant_code,
        collected_from=day_start,
        collected_to=day_end,
    )
    if not readings:
        return pd.DataFrame(
            columns=[
                "plant_code",
                "collected_at",
                "pv_production_kw",
                "grid_export_kw",
                "consumption_kw",
                "synced_at",
                "self_consumed_kw",
                "grid_import_kw",
            ]
        )

    df = pd.DataFrame(_plant_reading_rows(readings))
    df["collected_at"] = df["collected_at"].dt.tz_convert(tz)
    df["self_consumed_kw"] = df["pv_production_kw"] - df["grid_export_kw"]
    df["grid_import_kw"] = (df["consumption_kw"] - df["pv_production_kw"]).clip(lower=0)
    return df


def aggregate_hourly_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """Sum five-minute power readings into hourly energy totals.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_day_data`` for a single day.

    Returns
    -------
    pandas.DataFrame
        One row per hour with ``collected_at`` at the hour start and
        ``self_consumed_kwh``, ``grid_export_kwh``, and ``grid_import_kwh``.
    """
    columns = [
        "collected_at",
        "self_consumed_kwh",
        "grid_export_kwh",
        "grid_import_kwh",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    hourly = df.set_index("collected_at")
    for kw_column, kwh_column in (
        ("self_consumed_kw", "self_consumed_kwh"),
        ("grid_export_kw", "grid_export_kwh"),
        ("grid_import_kw", "grid_import_kwh"),
    ):
        hourly[kwh_column] = hourly[kw_column] * _INTERVAL_HOURS

    return hourly[list(columns[1:])].resample("h").sum().reset_index()


def build_daily_chart(df: pd.DataFrame, *, detail: bool = False) -> go.Figure:
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
    bar_width = _FIVE_MINUTES_MS if detail else _ONE_HOUR_MS
    fig = go.Figure()
    if df.empty:
        fig.update_layout(
            barmode="stack",
            xaxis_title="Heure",
            yaxis_title=yaxis_title,
            hovermode="x unified",
        )
        return fig

    if detail:
        chart_df = df
        series = _SERIES
    else:
        chart_df = aggregate_hourly_energy_kwh(df)
        series = (
            ("self_consumed_kwh", _SERIES[0][1], _SERIES[0][2]),
            ("grid_export_kwh", _SERIES[1][1], _SERIES[1][2]),
            ("grid_import_kwh", _SERIES[2][1], _SERIES[2][2]),
        )

    for index, (column, label, color) in enumerate(series):
        fig.add_trace(
            go.Bar(
                x=chart_df["collected_at"],
                y=chart_df[column],
                name=label,
                legendrank=index,
                marker_color=color,
                width=bar_width,
            )
        )

    fig.update_layout(
        barmode="stack",
        xaxis_title="Heure",
        yaxis_title=yaxis_title,
        hovermode="x unified",
        legend={"traceorder": "normal"},
        legend_title_text="",
    )
    return fig


def summarize_daily_energy_kwh(
    df: pd.DataFrame,
) -> list[tuple[str, float, str, str]]:
    """Return labeled daily energy totals with chart-matching colors.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_day_data`` for a single day.

    Returns
    -------
    list[tuple[str, float, str, str]]
        ``(label, kwh, foreground_hex, background_hex)`` per energy flow.
    """
    totals: list[tuple[str, float, str, str]] = []
    for column, label, fg_color in _SERIES:
        if df.empty:
            kwh = 0.0
        else:
            kwh = df[column].sum() * _INTERVAL_HOURS
        totals.append((label, kwh, fg_color, _SERIES_BG_COLORS[column]))
    return totals


def build_daily_donut_chart(df: pd.DataFrame) -> go.Figure:
    """Build a donut chart of daily energy totals by flow.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_day_data`` for a single day.

    Returns
    -------
    plotly.graph_objects.Figure
        Donut chart with sector labels and percentage shares in kWh.
    """
    totals = summarize_daily_energy_kwh(df)
    slices = [
        (label, kwh, fg_color) for label, kwh, fg_color, _bg_color in totals if kwh > 0
    ]

    fig = go.Figure()
    total_kwh = _total_consumption_kwh(df)
    center_images, center_annotations = _donut_center_layout(total_kwh)
    if not slices:
        fig.update_layout(
            height=_DONUT_HEIGHT,
            margin=dict(t=15, b=60, l=15, r=15),
            images=center_images,
            annotations=center_annotations,
        )
        return fig

    labels, values, colors = zip(*slices, strict=True)
    # pull = [
    #     _DONUT_PULL if label == _SELF_CONSUMED_LABEL else 0
    #     for label in labels
    # ]
    pull = False
    # Slice sequence comes from ``labels``/``values`` with ``sort=False``.
    # ``direction`` only sets whether sectors are drawn clockwise or
    # counter-clockwise from the first slice, not their label order.
    fig.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            hole=_DONUT_HOLE,
            pull=pull,
            sort=False,
            direction="counterclockwise",
            legendrank=list(range(len(labels))),
            marker={"colors": list(colors)},
            textinfo="percent",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont={"size": _DONUT_TEXT_SIZE},
            hovertemplate=("%{label}<br>%{value:.1f} kWh<br>%{percent}<extra></extra>"),
        )
    )
    fig.update_layout(
        height=_DONUT_HEIGHT,
        showlegend=True,
        legend={"traceorder": "normal"},
        margin=dict(t=10, b=60, l=10, r=10),
        images=center_images,
        annotations=center_annotations,
    )
    return fig
