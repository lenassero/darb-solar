"""Derived power and energy columns for plant power readings."""

from __future__ import annotations

import pandas as pd

from darb_solar.power.columns import (
    CONSUMPTION_KW,
    GRID_EXPORT_KW,
    GRID_IMPORT_KW,
    KW_TO_KWH_COLUMNS,
    PV_PRODUCTION_KW,
    SELF_CONSUMED_KW,
)
from darb_solar.power.constants import READING_INTERVAL_HOURS


def with_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with derived power flows and interval energy.

    Adds ``self_consumed_kw`` and ``grid_import_kw`` from the raw meter
    series, then converts the relevant kW columns to per-interval kWh
    with ``READING_INTERVAL_HOURS``.

    Parameters
    ----------
    df : pandas.DataFrame
        Raw plant power readings with at least ``pv_production_kw``,
        ``grid_export_kw``, and ``consumption_kw``.

    Returns
    -------
    pandas.DataFrame
        Copy of ``df`` with derived kW and matching ``*_kwh`` columns.
    """
    out = df.copy()
    out[SELF_CONSUMED_KW] = out[PV_PRODUCTION_KW] - out[GRID_EXPORT_KW]
    out[GRID_IMPORT_KW] = (out[CONSUMPTION_KW] - out[PV_PRODUCTION_KW]).clip(lower=0)
    for kw_column, kwh_column in KW_TO_KWH_COLUMNS:
        out[kwh_column] = out[kw_column] * READING_INTERVAL_HOURS
    return out
