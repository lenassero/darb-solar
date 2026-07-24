"""Thin FusionSolar API fetch helpers."""

from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

from darb_solar.db import Device
from darb_solar.fusionsolar import HISTORY_MAX_WINDOW_MS
from darb_solar.history_sync.session import FusionSolarSession

_TRANSIENT_MAX_RETRIES = 2
_TRANSIENT_BACKOFF_SECONDS = (5.0, 15.0)


def _history_ms_chunks(
    start_ms: int,
    end_ms: int,
    *,
    max_window_ms: int = HISTORY_MAX_WINDOW_MS,
) -> list[tuple[int, int]]:
    """Split ``[start_ms, end_ms)`` into API-sized history windows.

    FusionSolar allows at most 24 hours per history call. Plant-local
    calendar days are normally 24h, but ``Africa/Casablanca`` changes
    offset around Ramadan (e.g. UTC+1 → UTC+0). On those fall-back days
    local midnight→midnight is 25 hours in UTC, so one day window must
    be split into two API calls (24h + remainder).

    Parameters
    ----------
    start_ms : int
        Inclusive start timestamp in milliseconds.
    end_ms : int
        Exclusive end timestamp in milliseconds.
    max_window_ms : int, optional
        Maximum span per FusionSolar history call (24 hours).

    Returns
    -------
    list[tuple[int, int]]
        Contiguous ``(chunk_start_ms, chunk_end_ms)`` pairs.
    """
    if start_ms >= end_ms:
        return []
    chunks: list[tuple[int, int]] = []
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + max_window_ms, end_ms)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def _fetch_station(
    session: FusionSolarSession,
    plant_code: str,
) -> dict[str, Any]:
    """Return the FusionSolar station row for ``plant_code``.

    Parameters
    ----------
    session : FusionSolarSession
        Authenticated FusionSolar session.
    plant_code : str
        FusionSolar plant code.

    Returns
    -------
    dict[str, Any]
        Station metadata from ``list_stations``.

    Raises
    ------
    ValueError
        If the plant is not returned by the API.
    """
    stations = session.client.list_stations(page_no=1)
    for station in stations.get("list", []):
        if station.get("plantCode") == plant_code:
            return station
    raise ValueError(f"Plant {plant_code!r} was not found via list_stations.")


def _fetch_device_history_chunk(
    session: FusionSolarSession,
    device: Device,
    *,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Fetch one history window that already fits the API max span."""
    max_transient_retries = _TRANSIENT_MAX_RETRIES
    for transient_retry in range(max_transient_retries + 1):
        try:
            session.ensure_logged_in()
            response = session.client.get_device_history(
                device.dev_dn,
                device.dev_type_id,
                start_ms,
                end_ms,
            )
            return response.records
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            if transient_retry == max_transient_retries:
                raise
            backoff_seconds = _TRANSIENT_BACKOFF_SECONDS[transient_retry]
            logger.warning(
                f"Transient network error for dev_id={device.dev_id} "
                f"retry {transient_retry + 1}/{max_transient_retries}: {exc}; "
                f"retrying in {backoff_seconds:.0f}s"
            )
            time.sleep(backoff_seconds)
    return []


def _fetch_device_history(
    session: FusionSolarSession,
    device: Device,
    *,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Fetch device history, chunking when a local day exceeds 24 hours.

    See ``_history_ms_chunks``: Casablanca Ramadan fall-back days are 25h long and must
    be split to satisfy the API limit.
    """
    chunks = _history_ms_chunks(start_ms, end_ms)
    if len(chunks) > 1:
        span_h = (end_ms - start_ms) / 3_600_000
        logger.info(
            f"Splitting history for dev_id={device.dev_id} into "
            f"{len(chunks)} call(s): local day spans {span_h:.0f}h "
            f"(Casablanca clock change; API max 24h)"
        )
    records: list[dict[str, Any]] = []
    for chunk_start_ms, chunk_end_ms in chunks:
        records.extend(
            _fetch_device_history_chunk(
                session,
                device,
                start_ms=chunk_start_ms,
                end_ms=chunk_end_ms,
            )
        )
    return records
