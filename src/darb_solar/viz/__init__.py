"""Plotly figures and dashboard helpers for the PV dashboard."""

from darb_solar.power.aggregates import (
    aggregate_daily_energy_kwh,
    aggregate_hourly_mean_energy_kwh,
    aggregate_monthly_energy_kwh,
)
from darb_solar.power.constants import CURRENCY_LABEL, ELECTRICITY_PRICE_MAD_PER_KWH
from darb_solar.power.loaders import (
    load_day_data,
    load_month_data,
    load_power_readings_df,
    load_year_data,
)
from darb_solar.power.metrics import (
    mean_daily_consumption_kwh,
    summarize_energy_kwh,
    total_savings_mad,
)
from darb_solar.viz.charts import build_energy_donut_chart, build_stacked_energy_chart
from darb_solar.viz.daily import build_daily_energy_chart
from darb_solar.viz.monthly import (
    build_hourly_mean_energy_chart,
    build_monthly_energy_chart,
)
from darb_solar.viz.yearly import build_yearly_energy_chart, build_yearly_savings_chart

summarize_daily_energy_kwh = summarize_energy_kwh

__all__ = [
    "CURRENCY_LABEL",
    "ELECTRICITY_PRICE_MAD_PER_KWH",
    "aggregate_daily_energy_kwh",
    "aggregate_hourly_mean_energy_kwh",
    "aggregate_monthly_energy_kwh",
    "build_daily_energy_chart",
    "build_energy_donut_chart",
    "build_hourly_mean_energy_chart",
    "build_monthly_energy_chart",
    "build_stacked_energy_chart",
    "build_yearly_energy_chart",
    "build_yearly_savings_chart",
    "load_day_data",
    "load_month_data",
    "load_power_readings_df",
    "load_year_data",
    "mean_daily_consumption_kwh",
    "summarize_daily_energy_kwh",
    "total_savings_mad",
    "summarize_energy_kwh",
]
