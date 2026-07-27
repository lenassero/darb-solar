"""Aggregate plant power readings into energy totals."""

from __future__ import annotations

import pandas as pd

from darb_solar.power.columns import (
    COLLECTED_AT,
    GRID_EXPORT_KWH,
    GRID_IMPORT_KWH,
    SELF_CONSUMED_KWH,
)

_ENERGY_KWH_COLUMNS = [
    SELF_CONSUMED_KWH,
    GRID_EXPORT_KWH,
    GRID_IMPORT_KWH,
]


def aggregate_hourly_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """Sum five-minute energy readings into hourly totals.

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
    columns = [COLLECTED_AT, *_ENERGY_KWH_COLUMNS]
    if df.empty:
        return pd.DataFrame(columns=columns)

    hourly = df.set_index(COLLECTED_AT)
    return hourly[_ENERGY_KWH_COLUMNS].resample("h").sum().reset_index()


def aggregate_daily_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """Sum five-minute energy readings into daily totals.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    pandas.DataFrame
        One row per calendar day with ``collected_at`` at midnight and
        ``self_consumed_kwh``, ``grid_export_kwh``, and ``grid_import_kwh``.
    """
    columns = [COLLECTED_AT, *_ENERGY_KWH_COLUMNS]
    if df.empty:
        return pd.DataFrame(columns=columns)

    daily = df.set_index(COLLECTED_AT)
    return daily[_ENERGY_KWH_COLUMNS].resample("D").sum().reset_index()


def aggregate_monthly_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """Sum five-minute energy readings into monthly totals.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    pandas.DataFrame
        One row per calendar month with ``collected_at`` at month start
        and ``self_consumed_kwh``, ``grid_export_kwh``, and
        ``grid_import_kwh``.
    """
    columns = [COLLECTED_AT, *_ENERGY_KWH_COLUMNS]
    if df.empty:
        return pd.DataFrame(columns=columns)

    monthly = df.set_index(COLLECTED_AT)
    return monthly[_ENERGY_KWH_COLUMNS].resample("MS").sum().reset_index()


def aggregate_hourly_mean_energy_kwh(df: pd.DataFrame) -> pd.DataFrame:
    """Return mean energy kWh per hour-of-day across distinct dates.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    pandas.DataFrame
        One row per hour (0–23) with ``hour``, ``self_consumed_kwh``,
        ``grid_export_kwh``, and ``grid_import_kwh``.
    """
    columns = ["hour", *_ENERGY_KWH_COLUMNS]
    if df.empty:
        return pd.DataFrame(columns=columns)

    working = df.set_index(COLLECTED_AT)
    hourly = working[_ENERGY_KWH_COLUMNS].resample("h").sum()
    hourly["hour"] = hourly.index.hour
    return hourly.groupby("hour", as_index=False)[_ENERGY_KWH_COLUMNS].mean()
