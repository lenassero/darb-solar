"""Plant power data loading, aggregation, and metrics."""

from darb_solar.power.aggregates import (
    aggregate_daily_energy_kwh,
    aggregate_hourly_energy_kwh,
    aggregate_hourly_mean_energy_kwh,
    aggregate_monthly_energy_kwh,
)
from darb_solar.power.columns import READING_COLUMNS
from darb_solar.power.constants import CURRENCY_LABEL, ELECTRICITY_PRICE_MAD_PER_KWH
from darb_solar.power.derived import with_derived_columns
from darb_solar.power.loaders import (
    load_day_data,
    load_month_data,
    load_power_readings_df,
    load_year_data,
)
from darb_solar.power.metrics import (
    mean_daily_consumption_kwh,
    summarize_energy_kwh,
    total_consumption_kwh,
    total_savings_mad,
    with_savings_mad,
)

__all__ = [
    "CURRENCY_LABEL",
    "ELECTRICITY_PRICE_MAD_PER_KWH",
    "READING_COLUMNS",
    "aggregate_daily_energy_kwh",
    "aggregate_hourly_energy_kwh",
    "aggregate_hourly_mean_energy_kwh",
    "aggregate_monthly_energy_kwh",
    "load_day_data",
    "load_month_data",
    "load_power_readings_df",
    "load_year_data",
    "mean_daily_consumption_kwh",
    "summarize_energy_kwh",
    "total_consumption_kwh",
    "total_savings_mad",
    "with_derived_columns",
    "with_savings_mad",
]
