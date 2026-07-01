"""Read queries for FusionSolar Postgres data."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from darb_solar.db.connection import DbSession
from darb_solar.db.models import (
    Device,
    DevicePowerReading,
    Plant,
    PlantPowerReading,
    SyncWindow,
)


def get_plant(
    session: DbSession,
    plant_code: str,
) -> Plant | None:
    """Return a plant row by ``plant_code``, or ``None`` if missing.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code, for example ``NE=182468888``.

    Returns
    -------
    Plant or None
        Plant metadata when present.
    """
    return session.scalar(
        select(Plant).where(Plant.plant_code == plant_code)
    )


def list_devices(
    session: DbSession,
    *,
    plant_code: str,
) -> list[Device]:
    """Return device rows registered for a plant.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.

    Returns
    -------
    list[Device]
        Devices ordered by ``role`` then ``dev_id``.
    """
    return list(
        session.scalars(
            select(Device)
            .where(Device.plant_code == plant_code)
            .order_by(Device.role, Device.dev_id)
        )
    )


def get_sync_window(
    session: DbSession,
    dev_id: str,
    window_start: datetime,
) -> SyncWindow | None:
    """Return a sync-window checkpoint row when it exists.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    dev_id : str
        FusionSolar device ID.
    window_start : datetime
        Inclusive window start timestamp.

    Returns
    -------
    SyncWindow or None
        Checkpoint row when present.
    """
    return session.scalar(
        select(SyncWindow).where(
            SyncWindow.dev_id == dev_id,
            SyncWindow.window_start == window_start,
        )
    )


def get_latest_collected_at(
    session: DbSession,
    dev_id: str,
) -> datetime | None:
    """Return the most recent ``collected_at`` for a device, if any.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    dev_id : str
        FusionSolar device ID.

    Returns
    -------
    datetime or None
        Latest ``collected_at`` timestamp, or ``None`` when the device has no
        readings.
    """
    return session.scalar(
        select(DevicePowerReading.collected_at)
        .where(DevicePowerReading.dev_id == dev_id)
        .order_by(DevicePowerReading.collected_at.desc())
        .limit(1)
    )


def get_latest_plant_synced_at(
    session: DbSession,
    *,
    plant_code: str,
    collected_from: datetime,
    collected_to: datetime,
) -> datetime | None:
    """Return the latest ``synced_at`` for plant readings in a time range.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    collected_from : datetime
        Inclusive lower bound on ``collected_at``.
    collected_to : datetime
        Exclusive upper bound on ``collected_at``.

    Returns
    -------
    datetime or None
        Latest ``synced_at`` timestamp in the range, or ``None`` when no plant
        readings exist.
    """
    return session.scalar(
        select(func.max(PlantPowerReading.synced_at)).where(
            PlantPowerReading.plant_code == plant_code,
            PlantPowerReading.collected_at >= collected_from,
            PlantPowerReading.collected_at < collected_to,
        )
    )


def list_device_power_readings(
    session: DbSession,
    *,
    dev_id: str,
    collected_from: datetime,
    collected_to: datetime,
) -> list[DevicePowerReading]:
    """Return device readings within a half-open ``[collected_from, collected_to)`` range.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    dev_id : str
        FusionSolar device ID.
    collected_from : datetime
        Inclusive lower bound.
    collected_to : datetime
        Exclusive upper bound.

    Returns
    -------
    list[DevicePowerReading]
        Readings ordered by ``collected_at``.
    """
    return list(
        session.scalars(
            select(DevicePowerReading)
            .where(
                DevicePowerReading.dev_id == dev_id,
                DevicePowerReading.collected_at >= collected_from,
                DevicePowerReading.collected_at < collected_to,
            )
            .order_by(DevicePowerReading.collected_at)
        )
    )


def list_plant_power_readings(
    session: DbSession,
    *,
    plant_code: str,
    collected_from: datetime,
    collected_to: datetime,
) -> list[PlantPowerReading]:
    """Return plant readings within a half-open ``[collected_from, collected_to)`` range.

    Parameters
    ----------
    session : DbSession
        Open SQLAlchemy session.
    plant_code : str
        FusionSolar plant code.
    collected_from : datetime
        Inclusive lower bound.
    collected_to : datetime
        Exclusive upper bound.

    Returns
    -------
    list[PlantPowerReading]
        Readings ordered by ``collected_at``.
    """
    return list(
        session.scalars(
            select(PlantPowerReading)
            .where(
                PlantPowerReading.plant_code == plant_code,
                PlantPowerReading.collected_at >= collected_from,
                PlantPowerReading.collected_at < collected_to,
            )
            .order_by(PlantPowerReading.collected_at)
        )
    )
