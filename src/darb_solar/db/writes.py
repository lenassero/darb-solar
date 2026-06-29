"""Write queries for FusionSolar SQLite data."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from darb_solar.db.connection import get_connection
from darb_solar.db.sql import (
    UPSERT_DEVICE_POWER_READING_SQL,
    UPSERT_DEVICE_SQL,
    UPSERT_PLANT_POWER_READING_SQL,
    UPSERT_PLANT_SQL,
    UPSERT_SYNC_WINDOW_SQL,
)
from darb_solar.db.types import (
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
)


def _upsert_many(
    sql: str,
    rows: Iterable[object],
    *,
    db_path: Path | None = None,
) -> int:
    rows_list = list(rows)
    if not rows_list:
        return 0

    with get_connection(db_path) as connection:
        connection.executemany(sql, rows_list)
        connection.commit()
    return len(rows_list)


def upsert_plant(
    connection: sqlite3.Connection,
    plant: Plant,
) -> None:
    """Insert or update a single plant row.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    plant : Plant
        Plant metadata to store.
    """
    connection.execute(UPSERT_PLANT_SQL, plant)


def upsert_plants(
    plants: Iterable[Plant],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or update many plant rows in one transaction.

    Parameters
    ----------
    plants : Iterable[Plant]
        Plant metadata records to store.
    db_path : Path or None, optional
        Path to the SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    return _upsert_many(UPSERT_PLANT_SQL, plants, db_path=db_path)


def upsert_device(
    connection: sqlite3.Connection,
    device: Device,
) -> None:
    """Insert or update a single device row.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    device : Device
        Device metadata to store.
    """
    connection.execute(UPSERT_DEVICE_SQL, device)


def upsert_devices(
    devices: Iterable[Device],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or update many device rows in one transaction.

    Parameters
    ----------
    devices : Iterable[Device]
        Device metadata records to store.
    db_path : Path or None, optional
        Path to the SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    return _upsert_many(UPSERT_DEVICE_SQL, devices, db_path=db_path)


def upsert_device_power_reading(
    connection: sqlite3.Connection,
    reading: DevicePowerReading,
) -> None:
    """Insert or update a single device power reading.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    reading : DevicePowerReading
        Reading to store.
    """
    connection.execute(UPSERT_DEVICE_POWER_READING_SQL, reading)


def upsert_device_power_readings(
    readings: Iterable[DevicePowerReading],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or update many device power readings in one transaction.

    Parameters
    ----------
    readings : Iterable[DevicePowerReading]
        Readings to store.
    db_path : Path or None, optional
        Path to the SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    return _upsert_many(
        UPSERT_DEVICE_POWER_READING_SQL,
        readings,
        db_path=db_path,
    )


def upsert_plant_power_reading(
    connection: sqlite3.Connection,
    reading: PlantPowerReading,
) -> None:
    """Insert or update a single plant power reading.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    reading : PlantPowerReading
        Derived plant metrics to store.
    """
    connection.execute(UPSERT_PLANT_POWER_READING_SQL, reading)


def upsert_plant_power_readings(
    readings: Iterable[PlantPowerReading],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or update many plant power readings in one transaction.

    Parameters
    ----------
    readings : Iterable[PlantPowerReading]
        Derived plant metrics to store.
    db_path : Path or None, optional
        Path to the SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    return _upsert_many(
        UPSERT_PLANT_POWER_READING_SQL,
        readings,
        db_path=db_path,
    )


def upsert_sync_window(
    connection: sqlite3.Connection,
    window: SyncWindow,
) -> None:
    """Insert or update a single sync window checkpoint.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    window : SyncWindow
        Sync window state to store.
    """
    connection.execute(UPSERT_SYNC_WINDOW_SQL, window)


def upsert_sync_windows(
    windows: Iterable[SyncWindow],
    *,
    db_path: Path | None = None,
) -> int:
    """Insert or update many sync windows in one transaction.

    Parameters
    ----------
    windows : Iterable[SyncWindow]
        Sync window states to store.
    db_path : Path or None, optional
        Path to the SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    return _upsert_many(UPSERT_SYNC_WINDOW_SQL, windows, db_path=db_path)
