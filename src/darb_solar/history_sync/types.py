"""Dataclasses and enums for history and intraday sync runs.

Sync uses two status enums for day-based history:

- ``SyncWindowCheckpointStatus`` (``darb_solar.db``): persisted in
  ``sync_windows`` for resume. Values are ``pending``, ``done``, and ``failed``.
- ``SyncRunOutcome`` (this module): in-memory result for one sync unit
  (device-day window or intraday device fetch). Adds ``skipped`` when work is
  not performed this run.

When work runs, ``done`` and ``failed`` align across both; only the run layer
records ``skipped``, and only the DB layer records ``pending``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from darb_solar.db import Device, Plant


@dataclass(frozen=True)
class DayWindow:
    """One calendar day in the plant timezone."""

    day: date
    window_start: datetime
    window_end: datetime
    start_ms: int
    end_ms: int


class SyncRunOutcome(StrEnum):
    """Per-unit result for a sync attempt (not stored in DB).

    For day history, ``skipped`` means no fetch because a ``done`` checkpoint
    already exists. For intraday sync, ``skipped`` means the fetch range was
    shorter than the minimum gap. ``done`` and ``failed`` apply to both modes.
    """

    SKIPPED = "skipped"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class DeviceSyncResult:
    """Outcome of syncing one device for one unit of work."""

    readings_upserted: int
    outcome: SyncRunOutcome


@dataclass(frozen=True)
class SyncRunResult:
    """Summary counters for a history or intraday sync run."""

    synced: int
    skipped: int
    failed: int
    readings_upserted: int
    plant_readings_upserted: int
    plant_skipped: int = 0


@dataclass(frozen=True)
class BootstrapResult:
    """Plant and device rows written during bootstrap."""

    plant: Plant
    devices: list[Device]
