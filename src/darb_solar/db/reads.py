"""Read queries for FusionSolar SQLite data."""

from __future__ import annotations

import sqlite3

from darb_solar.db.types import (
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
    row_as,
)


def get_plant(
    connection: sqlite3.Connection,
    plant_code: str,
) -> Plant | None:
    """Return a plant row by ``plant_code``, or ``None`` if missing.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    plant_code : str
        FusionSolar plant code, for example ``NE=182468888``.

    Returns
    -------
    Plant or None
        Plant metadata when present.
    """
    row = connection.execute(
        """
        SELECT plant_code, plant_name, timezone
        FROM plants
        WHERE plant_code = ?
        """,
        (plant_code,),
    ).fetchone()
    if row is None:
        return None
    return row_as(row, Plant)


def list_devices(
    connection: sqlite3.Connection,
    *,
    plant_code: str,
) -> list[Device]:
    """Return device rows registered for a plant.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    plant_code : str
        FusionSolar plant code.

    Returns
    -------
    list[Device]
        Devices ordered by ``role`` then ``dev_id``.
    """
    rows = connection.execute(
        """
        SELECT dev_id, plant_code, dev_dn, dev_type_id, role
        FROM devices
        WHERE plant_code = ?
        ORDER BY role, dev_id
        """,
        (plant_code,),
    ).fetchall()
    return [row_as(row, Device) for row in rows]


def get_sync_window(
    connection: sqlite3.Connection,
    dev_id: str,
    window_start: str,
) -> SyncWindow | None:
    """Return a sync-window checkpoint row when it exists.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    dev_id : str
        FusionSolar device ID.
    window_start : str
        Inclusive window start as an ISO-8601 string.

    Returns
    -------
    SyncWindow or None
        Checkpoint row when present.
    """
    row = connection.execute(
        """
        SELECT dev_id, window_start, window_end, status, error_message, updated_at
        FROM sync_windows
        WHERE dev_id = ? AND window_start = ?
        """,
        (dev_id, window_start),
    ).fetchone()
    if row is None:
        return None
    return row_as(row, SyncWindow)


def get_latest_collected_at(
    connection: sqlite3.Connection,
    dev_id: str,
) -> str | None:
    """Return the most recent ``collected_at`` for a device, if any.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    dev_id : str
        FusionSolar device ID.

    Returns
    -------
    str or None
        Latest ``collected_at`` ISO-8601 timestamp, or ``None`` when the
        device has no readings.
    """
    row = connection.execute(
        """
        SELECT collected_at
        FROM device_power_readings
        WHERE dev_id = ?
        ORDER BY collected_at DESC
        LIMIT 1
        """,
        (dev_id,),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def get_latest_plant_synced_at(
    connection: sqlite3.Connection,
    *,
    plant_code: str,
    collected_from: str,
    collected_to: str,
) -> str | None:
    """Return the latest ``synced_at`` for plant readings in a time range.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    plant_code : str
        FusionSolar plant code.
    collected_from : str
        Inclusive lower bound on ``collected_at`` as an ISO-8601 timestamp.
    collected_to : str
        Exclusive upper bound on ``collected_at`` as an ISO-8601 timestamp.

    Returns
    -------
    str or None
        Latest ``synced_at`` ISO-8601 timestamp in the range, or ``None`` when
        no plant readings exist.
    """
    row = connection.execute(
        """
        SELECT MAX(synced_at)
        FROM plant_power_readings
        WHERE plant_code = ?
          AND collected_at >= ?
          AND collected_at < ?
        """,
        (plant_code, collected_from, collected_to),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return row[0]


def list_device_power_readings(
    connection: sqlite3.Connection,
    *,
    dev_id: str,
    collected_from: str,
    collected_to: str,
) -> list[DevicePowerReading]:
    """Return device readings within a half-open ``[collected_from, collected_to)`` range.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    dev_id : str
        FusionSolar device ID.
    collected_from : str
        Inclusive lower bound as an ISO-8601 timestamp.
    collected_to : str
        Exclusive upper bound as an ISO-8601 timestamp.

    Returns
    -------
    list[DevicePowerReading]
        Readings ordered by ``collected_at``.
    """
    rows = connection.execute(
        """
        SELECT dev_id, collected_at, active_power_kw, synced_at
        FROM device_power_readings
        WHERE dev_id = ?
          AND collected_at >= ?
          AND collected_at < ?
        ORDER BY collected_at
        """,
        (dev_id, collected_from, collected_to),
    ).fetchall()
    return [row_as(row, DevicePowerReading) for row in rows]


def list_plant_power_readings(
    connection: sqlite3.Connection,
    *,
    plant_code: str,
    collected_from: str,
    collected_to: str,
) -> list[PlantPowerReading]:
    """Return plant readings within a half-open ``[collected_from, collected_to)`` range.

    Parameters
    ----------
    connection : sqlite3.Connection
        Open SQLite connection.
    plant_code : str
        FusionSolar plant code.
    collected_from : str
        Inclusive lower bound as an ISO-8601 timestamp.
    collected_to : str
        Exclusive upper bound as an ISO-8601 timestamp.

    Returns
    -------
    list[PlantPowerReading]
        Readings ordered by ``collected_at``.
    """
    rows = connection.execute(
        """
        SELECT plant_code, collected_at, pv_production_kw,
               grid_export_kw, consumption_kw, synced_at
        FROM plant_power_readings
        WHERE plant_code = ?
          AND collected_at >= ?
          AND collected_at < ?
        ORDER BY collected_at
        """,
        (plant_code, collected_from, collected_to),
    ).fetchall()
    return [row_as(row, PlantPowerReading) for row in rows]
