"""Enumerations for FusionSolar Postgres columns."""

from __future__ import annotations

from enum import StrEnum


class DeviceRole(StrEnum):
    """Device role stored in the ``devices`` table CHECK constraint."""

    INVERTER = "inverter"
    METER = "meter"


class SyncWindowCheckpointStatus(StrEnum):
    """Durable checkpoint status for the ``sync_windows`` table.

    Tracks resume state across runs: ``pending`` while a fetch is in flight,
    ``done`` or ``failed`` when it finishes. See also ``SyncRunOutcome``
    in ``darb_solar.history_sync.types`` for per-run results that are not
    stored in the database (for example ``skipped``).
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
