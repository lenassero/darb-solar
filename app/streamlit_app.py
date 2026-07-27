"""Streamlit dashboard for daily and monthly plant power history."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from streamlit.connections import SQLConnection

# The package uses a src/ layout. When the Streamlit app is deployed from
# source, make ``src`` importable before importing ``darb_solar``.
_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from darb_solar.db import (  # noqa: E402
    PROJECT_ROOT,
    DbSession,
    get_latest_plant_collected_at,
    get_plant,
)
from darb_solar.power import (  # noqa: E402
    CURRENCY_LABEL,
    load_day_data,
    load_month_data,
    load_year_data,
)
from darb_solar.power.metrics import (  # noqa: E402
    mean_daily_consumption_kwh,
    summarize_energy_kwh,
    total_consumption_kwh,
    total_savings_mad,
)
from darb_solar.viz import (  # noqa: E402
    build_daily_energy_chart,
    build_energy_donut_chart,
    build_hourly_mean_energy_chart,
    build_monthly_energy_chart,
    build_yearly_energy_chart,
    build_yearly_savings_chart,
)

# Supabase may close the first connection while waking from idle.
_CONNECT_ATTEMPTS = 3
_CONNECT_RETRY_SECONDS = 1.5


def _resolve_streamlit_connection_name() -> str:
    """Return the Streamlit SQL connection name for dashboard reads.

    Returns
    -------
    str
        Connection name used with `st.connection()`. Defaults to `supabase`, a
        Streamlit-only SQL secret intended for the dashboard deployment.
    """
    return os.environ.get("DARB_SOLAR_STREAMLIT_SQL_CONNECTION", "supabase")


def _get_streamlit_sql_connection() -> SQLConnection:
    """Return the Streamlit-managed SQL connection for dashboard reads.

    Returns
    -------
    streamlit.connections.SQLConnection
        Cached SQL connection resolved from Streamlit secrets and optional
        environment configuration. Uses the same pool recycling settings as
        `darb_solar.db.get_engine` for idle Supabase drops.
    """
    return st.connection(
        _resolve_streamlit_connection_name(),
        type="sql",
        pool_pre_ping=True,
        pool_recycle=280,
    )


def _warmup_streamlit_connection(conn: SQLConnection) -> None:
    """Ping until the DB accepts a connection or retries are exhausted.

    Parameters
    ----------
    conn : SQLConnection
        Streamlit SQL connection that may fail on the first attempt while
        Supabase is waking from idle.
    """
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            with conn.session as session:
                session.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt >= _CONNECT_ATTEMPTS:
                raise
            time.sleep(_CONNECT_RETRY_SECONDS)
            conn.reset()


@contextmanager
def _get_streamlit_session() -> Iterator[DbSession]:
    """Yield a SQLAlchemy session sourced from Streamlit's SQL connection.

    Warms the connection with a short retry loop so a cold Supabase wake-up
    does not fail the first dashboard query.

    Yields
    ------
    DbSession
        SQLAlchemy session compatible with the existing `darb_solar.db.reads`
        helpers.
    """
    conn = _get_streamlit_sql_connection()
    _warmup_streamlit_connection(conn)
    with conn.session as session:
        yield cast(DbSession, session)


def _shift_selected_date(delta_days: int) -> None:
    st.session_state.selected_date += timedelta(days=delta_days)


def _shift_selected_month(delta_months: int) -> None:
    current = st.session_state.selected_month
    total_months = current.year * 12 + (current.month - 1) + delta_months
    year, month_index = divmod(total_months, 12)
    st.session_state.selected_month = date(year, month_index + 1, 1)


def _normalize_selected_month() -> None:
    selected = st.session_state.selected_month
    st.session_state.selected_month = date(selected.year, selected.month, 1)


def _shift_selected_year(delta_years: int) -> None:
    st.session_state.selected_year += delta_years


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return day_start, day_start + timedelta(days=1)


def _month_bounds(year: int, month: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    month_start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    month_end = datetime(next_year, next_month, 1, tzinfo=tz)
    return month_start, month_end


def _year_bounds(year: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    year_start = datetime(year, 1, 1, tzinfo=tz)
    year_end = datetime(year + 1, 1, 1, tzinfo=tz)
    return year_start, year_end


def _previous_month(year: int, month: int) -> tuple[int, int]:
    total_months = year * 12 + (month - 1) - 1
    prev_year, month_index = divmod(total_months, 12)
    return prev_year, month_index + 1


def _is_current_month(year: int, month: int, tz: ZoneInfo) -> bool:
    now = datetime.now(tz)
    return year == now.year and month == now.month


def _monthly_metric_labels(
    year: int,
    month: int,
    tz: ZoneInfo,
) -> tuple[str, str | None]:
    """Return a short delta caption and optional metric help text.

    ``delta_description`` is kept short because Streamlit truncates it with an ellipsis
    when the metric container is narrow.
    """
    delta_description = "vs. mois précédent"
    help_text = None
    if _is_current_month(year, month, tz):
        help_text = "Mois en cours : la comparaison porte sur une période incomplète."
    return delta_description, help_text


def _format_last_collected_at(collected_at: datetime | None, tz: ZoneInfo) -> str:
    # collected_at is the plant-metric sample time; show it in plant-local time.
    if collected_at is None:
        return "Aucune donnée synchronisée"
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=ZoneInfo("UTC"))
    local = collected_at.astimezone(tz)
    return local.strftime("%d/%m/%Y à %H:%M")


def _render_date_header(
    *,
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> date:
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = datetime.now(tz).date()

    _, nav_col, _ = st.columns([1, 2, 1])
    prev_col, date_col, next_col = nav_col.columns(
        [0.2, 1, 0.4],
    )

    prev_col.button(
        "◀",
        key="prev_day",
        on_click=_shift_selected_date,
        args=(-1,),
    )
    date_col.date_input("Date", key="selected_date", label_visibility="collapsed")
    next_col.button(
        "▶",
        key="next_day",
        on_click=_shift_selected_date,
        args=(1,),
    )

    selected_date = st.session_state.selected_date
    day_start, day_end = _day_bounds(selected_date, tz)
    collected_at = get_latest_plant_collected_at(
        session,
        plant_code=plant_code,
        collected_from=day_start,
        collected_to=day_end,
    )
    updated_label = _format_last_collected_at(collected_at, tz)
    with date_col:
        st.caption(f"Dernière mise à jour : {updated_label}")

    return selected_date


def _render_month_header(
    *,
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> tuple[int, int]:
    if "selected_month" not in st.session_state:
        now = datetime.now(tz)
        st.session_state.selected_month = date(now.year, now.month, 1)

    _, nav_col, _ = st.columns([1, 2, 1])
    prev_col, date_col, next_col = nav_col.columns(
        [0.2, 1, 0.4],
    )
    prev_col.button(
        "◀",
        key="prev_month",
        on_click=_shift_selected_month,
        args=(-1,),
    )
    date_col.date_input(
        "Mois",
        key="selected_month",
        label_visibility="collapsed",
        on_change=_normalize_selected_month,
    )
    next_col.button(
        "▶",
        key="next_month",
        on_click=_shift_selected_month,
        args=(1,),
    )

    selected = st.session_state.selected_month
    selected_month = date(selected.year, selected.month, 1)

    month_start, month_end = _month_bounds(
        selected_month.year,
        selected_month.month,
        tz,
    )
    collected_at = get_latest_plant_collected_at(
        session,
        plant_code=plant_code,
        collected_from=month_start,
        collected_to=month_end,
    )
    updated_label = _format_last_collected_at(collected_at, tz)
    with date_col:
        st.caption(f"Dernière mise à jour : {updated_label}")

    return selected_month.year, selected_month.month


def _donut_legend_layout() -> dict[str, object]:
    return {
        "orientation": "h",
        "yanchor": "top",
        "y": -0.02,
        "xanchor": "center",
        "x": 0.5,
    }


def _render_year_header(
    *,
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> int:
    """Render year navigation and return selected year.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    tz : ZoneInfo
        Plant-local timezone.

    Returns
    -------
    int
        Selected year from session state.
    """
    if "selected_year" not in st.session_state:
        now = datetime.now(tz)
        st.session_state.selected_year = now.year

    _, nav_col, _ = st.columns([1, 2, 1])
    prev_col, year_col, next_col = nav_col.columns(
        [0.2, 1, 0.4],
    )

    prev_col.button(
        "◀",
        key="prev_year",
        on_click=_shift_selected_year,
        args=(-1,),
    )
    _ = year_col.text_input(
        "Année",
        value=str(st.session_state.selected_year),
        label_visibility="collapsed",
    )
    next_col.button(
        "▶",
        key="next_year",
        on_click=_shift_selected_year,
        args=(1,),
    )

    year_start, year_end = _year_bounds(st.session_state.selected_year, tz)
    collected_at = get_latest_plant_collected_at(
        session,
        plant_code=plant_code,
        collected_from=year_start,
        collected_to=year_end,
    )
    updated_label = _format_last_collected_at(collected_at, tz)
    with year_col:
        st.caption(f"Dernière mise à jour : {updated_label}")

    return st.session_state.selected_year


def _render_day_view(
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> None:
    _, centered_col, _ = st.columns([1, 2, 1])
    with centered_col:
        selected_date = _render_date_header(
            session=session,
            plant_code=plant_code,
            tz=tz,
        )

    df = load_day_data(session, plant_code, selected_date, tz)
    if df.empty:
        st.info("Aucune donnée pour cette date.")
        return
    donut_fig = build_energy_donut_chart(
        summarize_energy_kwh(df),
        total_consumption_kwh(df),
    )
    donut_fig.update_layout(legend=_donut_legend_layout())
    with centered_col:
        st.plotly_chart(donut_fig, use_container_width=True)
    show_detail = st.toggle("Détail (5 min)", value=False)
    fig = build_daily_energy_chart(df, detail=show_detail)
    fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.28,
            "xanchor": "center",
            "x": 0.5,
        },
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"scrollZoom": True},
    )


def _render_month_view(
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> None:
    _, centered_col, _ = st.columns([1, 2, 1])
    with centered_col:
        year, month = _render_month_header(
            session=session,
            plant_code=plant_code,
            tz=tz,
        )

    df = load_month_data(session, plant_code, year, month, tz)
    if df.empty:
        st.info("Aucune donnée pour ce mois.")
        return

    current_mean_daily_consumption = mean_daily_consumption_kwh(df)
    current_savings = total_savings_mad(df)
    prev_year, prev_month = _previous_month(year, month)
    prev_df = load_month_data(session, plant_code, prev_year, prev_month, tz)
    consumption_delta = None
    savings_delta = None
    if not prev_df.empty:
        prev_mean = mean_daily_consumption_kwh(prev_df)
        consumption_delta = current_mean_daily_consumption - prev_mean
        savings_delta = current_savings - total_savings_mad(prev_df)
    delta_description, metric_help = _monthly_metric_labels(year, month, tz)

    donut_fig = build_energy_donut_chart(
        summarize_energy_kwh(df),
        total_consumption_kwh(df),
    )
    donut_fig.update_layout(legend=_donut_legend_layout())
    with centered_col:
        st.plotly_chart(donut_fig, use_container_width=True)
        metric_left, metric_right = st.columns(2)
        metric_left.metric(
            label="Consommation journalière moyenne",
            value=current_mean_daily_consumption,
            delta=consumption_delta,
            format="%.1f kWh",
            delta_description=delta_description,
            help=metric_help,
        )
        metric_right.metric(
            label="Économies réalisées",
            value=current_savings,
            delta=savings_delta,
            format=f"%.1f {CURRENCY_LABEL}",
            delta_description=delta_description,
            help=metric_help,
        )

    monthly_fig = build_monthly_energy_chart(df)
    monthly_fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.28,
            "xanchor": "center",
            "x": 0.5,
        },
        title="Consommation journalière",
    )
    st.plotly_chart(
        monthly_fig,
        use_container_width=True,
        config={"scrollZoom": True},
    )

    hourly_fig = build_hourly_mean_energy_chart(df)
    hourly_fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.28,
            "xanchor": "center",
            "x": 0.5,
        },
        title="Consommation horaire moyenne",
    )
    st.plotly_chart(
        hourly_fig,
        use_container_width=True,
        config={"scrollZoom": True},
    )


def _render_year_view(
    session: DbSession,
    plant_code: str,
    tz: ZoneInfo,
) -> None:
    """Render yearly aggregation view with consumption and savings metrics.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    tz : ZoneInfo
        Plant-local timezone.
    """
    _, centered_col, _ = st.columns([1, 2, 1])
    with centered_col:
        year = _render_year_header(
            session=session,
            plant_code=plant_code,
            tz=tz,
        )

    df = load_year_data(session, plant_code, year, tz)
    if df.empty:
        st.info("Aucune donnée pour cette année.")
        return

    current_mean_daily_consumption = mean_daily_consumption_kwh(df)
    current_savings = total_savings_mad(df)

    donut_fig = build_energy_donut_chart(
        summarize_energy_kwh(df),
        total_consumption_kwh(df),
    )
    donut_fig.update_layout(legend=_donut_legend_layout())
    with centered_col:
        st.plotly_chart(donut_fig, use_container_width=True)
        metric_left, metric_right = st.columns(2)
        metric_left.metric(
            label="Consommation journalière moyenne",
            value=current_mean_daily_consumption,
            format="%.1f kWh",
        )
        metric_right.metric(
            label="Économies réalisées",
            value=current_savings,
            format=f"%.1f {CURRENCY_LABEL}",
        )

    yearly_fig = build_yearly_energy_chart(df)
    yearly_fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.28,
            "xanchor": "center",
            "x": 0.5,
        },
        title="Consommation mensuelle",
    )
    st.plotly_chart(
        yearly_fig,
        use_container_width=True,
        config={"scrollZoom": True},
    )

    savings_fig = build_yearly_savings_chart(df)
    savings_fig.update_layout(
        title="Économies réalisées mensuellement",
    )
    st.plotly_chart(
        savings_fig,
        use_container_width=True,
        config={"scrollZoom": True},
    )


def main() -> None:
    """Run the PV history dashboard."""
    load_dotenv(PROJECT_ROOT / ".env")

    st.set_page_config(page_title="Darb Solar", layout="wide")
    st.title("Production et consommation solaires")

    plant_code = os.environ.get("DARB_SOLAR_PLANT_CODE")
    if not plant_code:
        st.error("Set DARB_SOLAR_PLANT_CODE in the environment or .env file.")
        return

    with _get_streamlit_session() as session:
        plant = get_plant(session, plant_code)
        if plant is None:
            st.error(
                f"Plant {plant_code!r} is not in the database. "
                "Run scripts/bootstrap_plant.py first."
            )
            return

        tz = ZoneInfo(plant.timezone)
        tab_jour, tab_mois, tab_annee = st.tabs(["Jour", "Mois", "Année"])
        with tab_jour:
            _render_day_view(session, plant_code, tz)
        with tab_mois:
            _render_month_view(session, plant_code, tz)
        with tab_annee:
            _render_year_view(session, plant_code, tz)


if __name__ == "__main__":
    main()
