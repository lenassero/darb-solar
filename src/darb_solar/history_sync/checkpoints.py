"""Sync-window checkpoint skip and persist logic.

Reads and writes ``SyncWindowCheckpointStatus`` in ``sync_windows``. Run-level
``SyncRunOutcome.SKIPPED`` is decided here but is not persisted.
"""

from __future__ import annotations

from datetime import datetime

from darb_solar.db import (
    DbSession,
    SyncWindow,
    SyncWindowCheckpointStatus,
    get_sync_window,
    upsert_sync_window,
    utc_now,
)


def should_skip_window(
    session: DbSession,
    *,
    dev_id: str,
    window_start: datetime,
    resume: bool,
) -> bool:
    if not resume:
        return False
    window = get_sync_window(session, dev_id, window_start)
    return window is not None and window.status == SyncWindowCheckpointStatus.DONE


def persist_sync_window(
    session: DbSession,
    *,
    dev_id: str,
    window_start: datetime,
    window_end: datetime,
    status: SyncWindowCheckpointStatus,
    error_message: str | None,
) -> None:
    upsert_sync_window(
        session,
        SyncWindow(
            dev_id=dev_id,
            window_start=window_start,
            window_end=window_end,
            status=status,
            error_message=error_message,
            updated_at=utc_now(),
        ),
    )
