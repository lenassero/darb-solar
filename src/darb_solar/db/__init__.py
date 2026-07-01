"""SQLAlchemy-backed Postgres storage for FusionSolar historical data."""

from darb_solar.db.connection import (
    DEFAULT_DATABASE_URL,
    DEFAULT_TIMEZONE_NAME,
    DbSession,
    PROJECT_ROOT,
    get_engine,
    get_session,
    resolve_database_url,
)
from darb_solar.db.models import (
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
)
from darb_solar.db.types import DeviceRole, SyncWindowCheckpointStatus
from darb_solar.db.reads import (
    get_latest_collected_at,
    get_latest_plant_synced_at,
    get_plant,
    get_sync_window,
    list_device_power_readings,
    list_devices,
    list_plant_power_readings,
)
from darb_solar.db.time import utc_now
from darb_solar.db.writes import (
    upsert_device,
    upsert_device_power_reading,
    upsert_plant,
    upsert_plant_power_reading,
    upsert_sync_window,
)

__all__ = [
    "DEFAULT_DATABASE_URL",
    "DEFAULT_TIMEZONE_NAME",
    "PROJECT_ROOT",
    "Device",
    "DevicePowerReading",
    "DeviceRole",
    "Plant",
    "PlantPowerReading",
    "SyncWindow",
    "SyncWindowCheckpointStatus",
    "DbSession",
    "get_engine",
    "get_session",
    "get_latest_collected_at",
    "get_latest_plant_synced_at",
    "get_plant",
    "get_sync_window",
    "list_device_power_readings",
    "list_devices",
    "list_plant_power_readings",
    "resolve_database_url",
    "upsert_device",
    "upsert_device_power_reading",
    "upsert_plant",
    "upsert_plant_power_reading",
    "upsert_sync_window",
    "utc_now",
]
