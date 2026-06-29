"""Sync-window checkpoint skip and persist logic.

Reads and writes ``SyncWindowCheckpointStatus`` in ``sync_windows``. Run-level
``SyncRunOutcome.SKIPPED`` is decided here but is not persisted.
"""

from __future__ import annotations

import sqlite3

from darb_solar.db import (
    SyncWindow,
    SyncWindowCheckpointStatus,
    get_sync_window,
    upsert_sync_window,
    utc_now_iso,
)


def should_skip_window(
    connection: sqlite3.Connection,
    *,
    dev_id: str,
    window_start: str,
    resume: bool,
) -> bool:
    if not resume:
        return False
    window = get_sync_window(connection, dev_id, window_start)
    return window is not None and window["status"] == SyncWindowCheckpointStatus.DONE


def persist_sync_window(
    connection: sqlite3.Connection,
    *,
    dev_id: str,
    window_start: str,
    window_end: str,
    status: SyncWindowCheckpointStatus,
    error_message: str | None,
) -> None:
    upsert_sync_window(
        connection,
        SyncWindow(
            dev_id=dev_id,
            window_start=window_start,
            window_end=window_end,
            status=status,
            error_message=error_message,
            updated_at=utc_now_iso(),
        ),
    )
