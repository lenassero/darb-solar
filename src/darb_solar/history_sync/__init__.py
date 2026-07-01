"""Extract, transform, and load FusionSolar device history into Postgres."""

from __future__ import annotations

from darb_solar.history_sync.session import FusionSolarSession, login_fusionsolar
from darb_solar.history_sync.sync import bootstrap_plant, sync_history
from darb_solar.history_sync.types import (
    BootstrapResult,
    DayWindow,
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)

__all__ = [
    "BootstrapResult",
    "DayWindow",
    "DeviceSyncResult",
    "FusionSolarSession",
    "SyncRunOutcome",
    "SyncRunResult",
    "bootstrap_plant",
    "login_fusionsolar",
    "sync_history",
]
