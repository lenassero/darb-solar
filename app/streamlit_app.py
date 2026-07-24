"""Streamlit dashboard for daily plant power history."""

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
from darb_solar.viz.daily import (  # noqa: E402
    build_daily_chart,
    build_daily_donut_chart,
    load_day_data,
)

# Supabase may close the first connection while waking from idle.
_CONNECT_ATTEMPTS = 3
_CONNECT_RETRY_SECONDS = 1.5


def _format_kwh(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


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


def _render_colored_metric(
    container: st.delta_generator.DeltaGenerator,
    *,
    label: str,
    value_kwh: float,
    fg_color: str,
    bg_color: str,
) -> None:
    formatted = _format_kwh(value_kwh)
    container.markdown(
        (
            f'<div style="background-color:{bg_color};color:{fg_color};'
            'padding:0.75rem 1rem;border-radius:0.75rem;">'
            f'<span style="font-size:1.5rem;font-weight:700;">{formatted}</span>'
            f"<span> kWh {label}</span></div>"
        ),
        unsafe_allow_html=True,
    )


def _render_energy_totals(
    totals: list[tuple[str, float, str, str]],
) -> None:
    top_left, top_right = st.columns(2)
    for container, total in zip((top_left, top_right), totals[:2], strict=True):
        label, kwh, fg_color, bg_color = total
        _render_colored_metric(
            container,
            label=label,
            value_kwh=kwh,
            fg_color=fg_color,
            bg_color=bg_color,
        )

    _, bottom_center, _ = st.columns([1, 2, 1])
    label, kwh, fg_color, bg_color = totals[2]
    _render_colored_metric(
        bottom_center,
        label=label,
        value_kwh=kwh,
        fg_color=fg_color,
        bg_color=bg_color,
    )


def _shift_selected_date(days: int) -> None:
    st.session_state.selected_date += timedelta(days=days)


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return day_start, day_start + timedelta(days=1)


def _format_last_updated(collected_at: datetime | None, tz: ZoneInfo) -> str:
    # collected_at is the plant-metric sample time; show it in plant-local time.
    if collected_at is None:
        return "aucune donnée synchronisée"
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
    updated_label = _format_last_updated(collected_at, tz)
    with date_col:
        st.caption(f"Dernière mise à jour : {updated_label}")

    return selected_date


def main() -> None:
    """Run the daily PV history dashboard."""
    load_dotenv(PROJECT_ROOT / ".env")

    st.set_page_config(page_title="Darb Solar", layout="wide")
    st.title("Production solaire")

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
        _, centered_col, _ = st.columns([1, 2, 1])
        with centered_col:
            selected_date = _render_date_header(
                session=session,
                plant_code=plant_code,
                tz=tz,
            )

        df = load_day_data(session, plant_code, selected_date, tz)
        if df.empty:
            st.info("No data for this date.")
            return
        donut_fig = build_daily_donut_chart(df)
        donut_fig.update_layout(
            legend={
                "orientation": "h",
                "yanchor": "top",
                "y": -0.02,
                "xanchor": "center",
                "x": 0.5,
            }
        )
        with centered_col:
            st.plotly_chart(donut_fig, use_container_width=True)
        show_detail = st.toggle("Détail (5 min)", value=False)
        fig = build_daily_chart(df, detail=show_detail)
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


if __name__ == "__main__":
    main()
