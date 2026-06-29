"""Incremental FusionSolar history sync for the current calendar day."""

from __future__ import annotations

from darb_solar.history_sync.types import (
    DeviceSyncResult,
    SyncRunOutcome,
    SyncRunResult,
)
from darb_solar.intraday_sync.sync import sync_intraday

__all__ = [
    "DeviceSyncResult",
    "SyncRunOutcome",
    "SyncRunResult",
    "sync_intraday",
]
