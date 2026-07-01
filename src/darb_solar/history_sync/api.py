"""Thin FusionSolar API fetch helpers."""

from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

from darb_solar.db import Device
from darb_solar.history_sync.session import FusionSolarSession

_TRANSIENT_MAX_RETRIES = 2
_TRANSIENT_BACKOFF_SECONDS = (5.0, 15.0)


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


def _fetch_device_history(
    session: FusionSolarSession,
    device: Device,
    *,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
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
