"""Business metrics derived from plant power readings."""

from __future__ import annotations

import pandas as pd

from darb_solar.power.columns import (
    COLLECTED_AT,
    CONSUMPTION_KWH,
    SAVINGS_MAD,
    SELF_CONSUMED_KWH,
)
from darb_solar.power.constants import ELECTRICITY_PRICE_MAD_PER_KWH, KWH_SERIES


def total_consumption_kwh(df: pd.DataFrame) -> float:
    """Return total consumption kWh for a readings DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    float
        Sum of ``consumption_kwh``.
    """
    if df.empty:
        return 0.0
    return float(df[CONSUMPTION_KWH].sum())


def summarize_energy_kwh(
    df: pd.DataFrame,
) -> list[tuple[str, float, str]]:
    """Return labeled energy totals with chart-matching colors.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    list[tuple[str, float, str]]
        ``(label, kwh, color_hex)`` per energy flow.
    """
    totals: list[tuple[str, float, str]] = []
    for column, label, color in KWH_SERIES:
        if df.empty:
            kwh = 0.0
        else:
            kwh = float(df[column].sum())
        totals.append((label, kwh, color))
    return totals


def mean_daily_consumption_kwh(df: pd.DataFrame) -> float:
    """Return mean consumption kWh per day with at least one reading.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.

    Returns
    -------
    float
        Total consumption kWh divided by the count of distinct dates.
    """
    if df.empty:
        return 0.0
    distinct_dates = df[COLLECTED_AT].dt.date.nunique()
    if distinct_dates == 0:
        return 0.0
    return total_consumption_kwh(df) / distinct_dates


def with_savings_mad(
    df: pd.DataFrame,
    price: float = ELECTRICITY_PRICE_MAD_PER_KWH,
) -> pd.DataFrame:
    """Return a copy with ``savings_mad`` from self-consumed kWh.

    Parameters
    ----------
    df : pandas.DataFrame
        Readings or energy aggregates with ``self_consumed_kwh``.
    price : float, optional
        Electricity price in Moroccan dirham per kWh.

    Returns
    -------
    pandas.DataFrame
        Copy of ``df`` with ``savings_mad`` (``self_consumed_kwh``
        times ``price``).
    """
    out = df.copy()
    out[SAVINGS_MAD] = out[SELF_CONSUMED_KWH] * price
    return out


def total_savings_mad(
    df: pd.DataFrame,
    price: float = ELECTRICITY_PRICE_MAD_PER_KWH,
) -> float:
    """Return estimated total savings from self-consumed solar energy.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of ``load_power_readings_df`` for any interval.
    price : float, optional
        Electricity price in Moroccan dirham per kWh.

    Returns
    -------
    float
        Self-consumed solar energy in kWh multiplied by ``price``.
    """
    if df.empty:
        return 0.0
    return float(df[SELF_CONSUMED_KWH].sum()) * price
