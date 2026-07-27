"""Column-name schema for plant power readings DataFrames."""

from __future__ import annotations

from sqlalchemy import inspect

from darb_solar.db.models import PlantPowerReading

COLLECTED_AT = PlantPowerReading.collected_at.key
PV_PRODUCTION_KW = PlantPowerReading.pv_production_kw.key
GRID_EXPORT_KW = PlantPowerReading.grid_export_kw.key
CONSUMPTION_KW = PlantPowerReading.consumption_kw.key

SELF_CONSUMED_KW = "self_consumed_kw"
GRID_IMPORT_KW = "grid_import_kw"

SELF_CONSUMED_KWH = f"{SELF_CONSUMED_KW.removesuffix('_kw')}_kwh"
GRID_EXPORT_KWH = f"{GRID_EXPORT_KW.removesuffix('_kw')}_kwh"
GRID_IMPORT_KWH = f"{GRID_IMPORT_KW.removesuffix('_kw')}_kwh"
CONSUMPTION_KWH = f"{CONSUMPTION_KW.removesuffix('_kw')}_kwh"
SAVINGS_MAD = "savings_mad"

RAW_READING_COLUMNS = tuple(
    attr.key for attr in inspect(PlantPowerReading).mapper.column_attrs
)
DERIVED_KW_COLUMNS = (SELF_CONSUMED_KW, GRID_IMPORT_KW)
KW_TO_KWH_COLUMNS = (
    (SELF_CONSUMED_KW, SELF_CONSUMED_KWH),
    (GRID_EXPORT_KW, GRID_EXPORT_KWH),
    (GRID_IMPORT_KW, GRID_IMPORT_KWH),
    (CONSUMPTION_KW, CONSUMPTION_KWH),
)
DERIVED_KWH_COLUMNS = tuple(kwh for _kw, kwh in KW_TO_KWH_COLUMNS)
READING_COLUMNS = [
    *RAW_READING_COLUMNS,
    *DERIVED_KW_COLUMNS,
    *DERIVED_KWH_COLUMNS,
]
