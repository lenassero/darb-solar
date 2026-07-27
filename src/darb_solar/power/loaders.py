"""Load plant power readings into pandas DataFrames."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from darb_solar.db import DbSession
from darb_solar.db.models import PlantPowerReading
from darb_solar.power.columns import COLLECTED_AT, READING_COLUMNS
from darb_solar.power.derived import with_derived_columns


def load_power_readings_df(
    session: DbSession,
    plant_code: str,
    collected_from: datetime,
    collected_to: datetime,
    tz: ZoneInfo,
) -> pd.DataFrame:
    """Load plant power readings for a half-open interval with derived columns.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    collected_from : datetime
        Inclusive lower bound for ``collected_at``.
    collected_to : datetime
        Exclusive upper bound for ``collected_at``.
    tz : ZoneInfo
        Plant-local timezone used to convert ``collected_at``.

    Returns
    -------
    pandas.DataFrame
        Rows for ``[collected_from, collected_to)`` with raw plant
        readings plus derived kW and per-interval kWh columns.
    """
    stmt = (
        select(PlantPowerReading)
        .where(
            PlantPowerReading.plant_code == plant_code,
            PlantPowerReading.collected_at >= collected_from,
            PlantPowerReading.collected_at < collected_to,
        )
        .order_by(PlantPowerReading.collected_at)
    )
    df = pd.read_sql(stmt, session.connection())
    if df.empty:
        return pd.DataFrame(columns=READING_COLUMNS)

    # DB returns UTC; convert so charts/resamples use plant-local wall time.
    df[COLLECTED_AT] = df[COLLECTED_AT].dt.tz_convert(tz)
    return with_derived_columns(df)


def load_day_data(
    session: DbSession,
    plant_code: str,
    day: date,
    tz: ZoneInfo,
) -> pd.DataFrame:
    """Load plant power readings for one calendar day with energy columns.

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
        Rows for ``[day_start, day_end)`` with raw plant readings,
        derived kW columns, and per-interval kWh columns.
    """
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    return load_power_readings_df(
        session,
        plant_code,
        day_start,
        day_end,
        tz,
    )


def load_month_data(
    session: DbSession,
    plant_code: str,
    year: int,
    month: int,
    tz: ZoneInfo,
) -> pd.DataFrame:
    """Load plant power readings for one calendar month with energy.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    year : int
        Calendar year in the plant timezone.
    month : int
        Calendar month (1–12) in the plant timezone.
    tz : ZoneInfo
        Plant-local timezone used for month boundaries and the x-axis.

    Returns
    -------
    pandas.DataFrame
        Rows for ``[month_start, month_end)`` with raw plant readings,
        derived kW columns, and per-interval kWh columns.
        ``month_end`` is the first instant of the next calendar month
        and is exclusive.
    """
    month_start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    month_end = datetime(next_year, next_month, 1, tzinfo=tz)
    return load_power_readings_df(
        session,
        plant_code,
        month_start,
        month_end,
        tz,
    )


def load_year_data(
    session: DbSession,
    plant_code: str,
    year: int,
    tz: ZoneInfo,
) -> pd.DataFrame:
    """Load plant power readings for one calendar year with energy.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    year : int
        Calendar year in the plant timezone.
    tz : ZoneInfo
        Plant-local timezone used for year boundaries and the x-axis.

    Returns
    -------
    pandas.DataFrame
        Rows for ``[year_start, year_end)`` with raw plant readings,
        derived kW columns, and per-interval kWh columns. ``year_end``
        is the first instant of the next calendar year and is exclusive.
    """
    year_start = datetime(year, 1, 1, tzinfo=tz)
    year_end = datetime(year + 1, 1, 1, tzinfo=tz)
    return load_power_readings_df(
        session,
        plant_code,
        year_start,
        year_end,
        tz,
    )
