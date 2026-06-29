"""Typed row shapes for FusionSolar SQLite tables."""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from typing import Literal, TypeVar, TypedDict, cast

DeviceRole = Literal["inverter", "meter"]


class SyncWindowCheckpointStatus(StrEnum):
    """Durable checkpoint status for the ``sync_windows`` table.

    Tracks resume state across runs: ``pending`` while a fetch is in flight,
    ``done`` or ``failed`` when it finishes. See also ``SyncRunOutcome``
    in ``darb_solar.history_sync.types`` for per-run results that are not
    stored in SQLite (for example ``skipped``).
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"

T = TypeVar("T")


class Plant(TypedDict):
    """Row stored in the ``plants`` table."""

    plant_code: str
    plant_name: str
    timezone: str


class Device(TypedDict):
    """Row stored in the ``devices`` table."""

    dev_id: str
    plant_code: str
    dev_dn: str
    dev_type_id: int
    role: DeviceRole


class DevicePowerReading(TypedDict):
    """Row stored in the ``device_power_readings`` table."""

    dev_id: str
    collected_at: str
    active_power_kw: float
    synced_at: str


class PlantPowerReading(TypedDict):
    """Row stored in the ``plant_power_readings`` table."""

    plant_code: str
    collected_at: str
    pv_production_kw: float
    grid_export_kw: float
    consumption_kw: float
    synced_at: str


class SyncWindow(TypedDict):
    """Row stored in the ``sync_windows`` table.

    The ``status`` field uses ``SyncWindowCheckpointStatus`` only; run-only
    outcomes such as ``skipped`` never appear here.
    """

    dev_id: str
    window_start: str
    window_end: str
    status: SyncWindowCheckpointStatus
    error_message: str | None
    updated_at: str


def row_as(row: sqlite3.Row, cls: type[T]) -> T:
    """Map a ``sqlite3.Row`` to a ``TypedDict`` when column names match."""
    return cast(T, dict(row))
