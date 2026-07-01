"""Write queries for FusionSolar Postgres data."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert

from darb_solar.db.connection import DbSession
from darb_solar.db.models import (
    Base,
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
)

_PLANT_UPSERT = insert(Plant).on_conflict_do_update(
    index_elements=[Plant.plant_code],
    set_={
        "plant_name": insert(Plant).excluded.plant_name,
        "timezone": insert(Plant).excluded.timezone,
    },
)

_DEVICE_UPSERT = insert(Device).on_conflict_do_update(
    index_elements=[Device.dev_id],
    set_={
        "plant_code": insert(Device).excluded.plant_code,
        "dev_dn": insert(Device).excluded.dev_dn,
        "dev_type_id": insert(Device).excluded.dev_type_id,
        "role": insert(Device).excluded.role,
    },
)

_DEVICE_POWER_READING_UPSERT = insert(DevicePowerReading).on_conflict_do_update(
    index_elements=[
        DevicePowerReading.dev_id,
        DevicePowerReading.collected_at,
    ],
    set_={
        "active_power_kw": insert(DevicePowerReading).excluded.active_power_kw,
        "synced_at": insert(DevicePowerReading).excluded.synced_at,
    },
)

_PLANT_POWER_READING_UPSERT = insert(PlantPowerReading).on_conflict_do_update(
    index_elements=[
        PlantPowerReading.plant_code,
        PlantPowerReading.collected_at,
    ],
    set_={
        "pv_production_kw": insert(PlantPowerReading).excluded.pv_production_kw,
        "grid_export_kw": insert(PlantPowerReading).excluded.grid_export_kw,
        "consumption_kw": insert(PlantPowerReading).excluded.consumption_kw,
        "synced_at": insert(PlantPowerReading).excluded.synced_at,
    },
)

_SYNC_WINDOW_UPSERT = insert(SyncWindow).on_conflict_do_update(
    index_elements=[SyncWindow.dev_id, SyncWindow.window_start],
    set_={
        "window_end": insert(SyncWindow).excluded.window_end,
        "status": insert(SyncWindow).excluded.status,
        "error_message": insert(SyncWindow).excluded.error_message,
        "updated_at": insert(SyncWindow).excluded.updated_at,
    },
)


def _as_mapping(instance: Base) -> dict[str, Any]:
    """Return column values from an ORM instance for upsert."""
    return {
        attr.key: getattr(instance, attr.key)
        for attr in sa_inspect(instance).mapper.column_attrs
    }


def _upsert(session: DbSession, upsert_stmt: object, instance: Base) -> None:
    session.execute(upsert_stmt, _as_mapping(instance))


def upsert_plant(
    session: DbSession,
    plant: Plant,
) -> None:
    """Insert or update a plant row.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session. Caller owns ``commit()``.
    plant : Plant
        Plant metadata to store.
    """
    _upsert(session, _PLANT_UPSERT, plant)


def upsert_device(
    session: DbSession,
    device: Device,
) -> None:
    """Insert or update a device row.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session. Caller owns ``commit()``.
    device : Device
        Device metadata to store.
    """
    _upsert(session, _DEVICE_UPSERT, device)


def upsert_device_power_reading(
    session: DbSession,
    reading: DevicePowerReading,
) -> None:
    """Insert or update a device power reading.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session. Caller owns ``commit()``.
    reading : DevicePowerReading
        Reading to store.
    """
    _upsert(session, _DEVICE_POWER_READING_UPSERT, reading)


def upsert_plant_power_reading(
    session: DbSession,
    reading: PlantPowerReading,
) -> None:
    """Insert or update a plant power reading.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session. Caller owns ``commit()``.
    reading : PlantPowerReading
        Derived plant metrics to store.
    """
    _upsert(session, _PLANT_POWER_READING_UPSERT, reading)


def upsert_sync_window(
    session: DbSession,
    window: SyncWindow,
) -> None:
    """Insert or update a sync window checkpoint.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session. Caller owns ``commit()``.
    window : SyncWindow
        Sync window state to store.
    """
    _upsert(session, _SYNC_WINDOW_UPSERT, window)
