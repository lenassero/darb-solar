"""Streamlit dashboard for daily plant power history."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv
from streamlit.connections import SQLConnection

# The package uses a src/ layout. When the Streamlit app is deployed from
# source, make ``src`` importable before importing ``darb_solar``.
_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from darb_solar.db import (  # noqa: E402
    PROJECT_ROOT,
    DbSession,
    get_latest_plant_synced_at,
    get_plant,
)
from darb_solar.viz.daily import (  # noqa: E402
    build_daily_chart,
    build_daily_donut_chart,
    load_day_data,
)


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
        environment configuration.
    """
    return st.connection(_resolve_streamlit_connection_name(), type="sql")


@contextmanager
def _get_streamlit_session() -> Iterator[DbSession]:
    """Yield a SQLAlchemy session sourced from Streamlit's SQL connection.

    Yields
    ------
    DbSession
        SQLAlchemy session compatible with the existing `darb_solar.db.reads`
        helpers.
    """
    with _get_streamlit_sql_connection().session as session:
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


def _format_last_updated(synced_at: datetime | None, tz: ZoneInfo) -> str:
    # synced_at is stored as UTC by the sync CLI; show it in plant-local time.
    if synced_at is None:
        return "aucune donnée synchronisée"
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=ZoneInfo("UTC"))
    local = synced_at.astimezone(tz)
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
    synced_at = get_latest_plant_synced_at(
        session,
        plant_code=plant_code,
        collected_from=day_start,
        collected_to=day_end,
    )
    updated_label = _format_last_updated(synced_at, tz)
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
                "y": -0.02,
                "xanchor": "center",
                "x": 0.5,
            }
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"scrollZoom": True},
        )


if __name__ == "__main__":
    main()
